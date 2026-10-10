"""Experiment 5 benchmark: speed of the text-to-speech engines, and the audio for the listening test.

  python tts_bench.py                       # every engine whose key is in .env, 3 runs per sentence
  python tts_bench.py --engines el_flash,dg_aura2 --repeats 1
  python tts_bench.py --no-interrupt        # skip the cancel-mid-sentence test

Real API calls: 8 short sentences, about 70 characters each, a few cents in total.

Measured per request (one persistent connection per engine, like a running assistant):
  time to first audio  = from sending the text to the first ~0.1 s of audio arriving
  total time           = until the last audio byte arrived
  real-time factor     = total time / length of the audio (below 1 = faster than speaking)
The first request of each engine is also reported separately (it pays for opening the connection).
The audio of the first run of each sentence is saved to data/audio/ for listen_test.py.
Interruption test: start the longest sentence, drop the connection after ~0.5 s of audio, time how long
closing takes, and check that the next request still works.
"""
import argparse
import asyncio
import base64
import io
import json
import os
import statistics
import sys
import time
import wave
from contextlib import aclosing
from pathlib import Path

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AUDIO = HERE / "data" / "audio"
RESULTS = HERE / "results"
load_dotenv(ROOT / ".env")

# What the assistant would actually say. s1..s6 English, h1..h2 Hinglish (only engines that speak Hindi).
SENTENCES = {
    "s1": "Scrolling down.",
    "s2": "I found two sign in buttons. Which one do you want?",
    "s3": "The first book on this page is A Light in the Attic, priced at fifty-one pounds seventy-seven.",
    "s4": "Searching for MSI gaming monitors under twenty thousand rupees.",
    "s5": "I couldn't find that button. Do you want me to scroll down and try again?",
    "s6": "Done. The cheapest monitor on this page is the Acer Nitro, at twelve thousand four hundred and "
          "ninety-nine rupees, and it ships in two days.",
    "h1": "मैंने YouTube खोल दिया है। अब क्या search करूँ?",
    "h2": "ठीक है, मैं नीचे scroll कर रहा हूँ।",
}
HINGLISH = {"h1", "h2"}
EL_VOICE = "EXAVITQu4vr4xnSDxMaL"   # "Sarah", a female premade voice (all engines use a female voice)
MIN_BYTES_FOR_FIRST_AUDIO = 4800    # 0.1 s of 24 kHz 16-bit audio


class HttpError(RuntimeError):
    pass


async def post_stream(client, url, headers, payload):
    async with client.stream("POST", url, headers=headers, json=payload) as r:
        if r.status_code >= 400:
            body = (await r.aread())[:300].decode("utf-8", "replace")
            raise HttpError(f"HTTP {r.status_code}: {body}")
        async for chunk in r.aiter_bytes():
            if chunk:
                yield chunk


# Each engine: an async generator of audio bytes, plus how to read the result.
async def el_audio(client, text, sid, model):
    payload = {"text": text, "model_id": model}
    if sid in HINGLISH and model == "eleven_flash_v2_5":
        payload["language_code"] = "hi"
    async for c in post_stream(client, f"https://api.elevenlabs.io/v1/text-to-speech/{EL_VOICE}/stream?output_format=pcm_24000",
                               {"xi-api-key": os.getenv("ELEVENLABS_API_KEY")}, payload):
        yield c


async def dg_audio(client, text, sid, model):
    async for c in post_stream(client, f"https://api.deepgram.com/v1/speak?model={model}&encoding=linear16&sample_rate=24000&container=none",
                               {"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}"}, {"text": text}):
        yield c


async def sarvam_rest_audio(client, text, sid, model):
    r = await client.post("https://api.sarvam.ai/text-to-speech", headers={"api-subscription-key": os.getenv("SARVAM_API_KEY")},
                          json={"text": text, "target_language_code": "hi-IN" if sid in HINGLISH else "en-IN",
                                "speaker": "ritu", "model": model})
    if r.status_code >= 400:
        raise HttpError(f"HTTP {r.status_code}: {r.text[:300]}")
    yield base64.b64decode(r.json()["audios"][0])      # arrives all at once: a complete WAV file


async def sarvam_stream_audio(client, text, sid, model):
    async for c in post_stream(client, "https://api.sarvam.ai/text-to-speech/stream", {"api-subscription-key": os.getenv("SARVAM_API_KEY")},
                               {"text": text, "target_language_code": "hi-IN" if sid in HINGLISH else "en-IN",
                                "speaker": "ritu", "model": model}):
        yield c


async def groq_audio(client, text, sid, model):
    async for c in post_stream(client, "https://api.groq.com/openai/v1/audio/speech", {"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"},
                               {"model": model, "input": text, "voice": "hannah", "response_format": "wav"}):
        yield c


class FluxSession:
    """Deepgram Flux TTS: one WebSocket kept open between sentences (opening it costs ~1.1 s)."""

    def __init__(self, model: str):
        self.model, self.ws = model, None
        self.interrupt_ms = None

    async def ensure(self):
        if self.ws is None:
            from websockets.asyncio.client import connect
            self.ws = await connect(f"wss://api.deepgram.com/v2/speak?model={self.model}&encoding=linear16&sample_rate=24000",
                                    additional_headers={"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}"}, max_size=None)
            json.loads(await self.ws.recv())   # {"type": "Connected", ...}

    async def interrupt(self):
        """Stop the sentence being spoken; the server answers with SpeechInterrupted and how much was played."""
        t = time.perf_counter()
        await self.ws.send(json.dumps({"type": "Interrupt"}))
        while True:
            m = await asyncio.wait_for(self.ws.recv(), 5)
            if not isinstance(m, bytes) and json.loads(m).get("type") == "SpeechInterrupted":
                break
        self.interrupt_ms = (time.perf_counter() - t) * 1000

    async def speak(self, text: str):
        await self.ensure()
        await self.ws.send(json.dumps({"type": "Speak", "text": text}))
        await self.ws.send(json.dumps({"type": "Flush"}))
        done = False
        try:
            while True:
                m = await asyncio.wait_for(self.ws.recv(), 20)
                if isinstance(m, bytes):
                    yield m
                    continue
                d = json.loads(m)
                if d.get("type") == "SpeechMetadata":     # arrives after the last audio frame of this sentence
                    done = True
                    return
                if d.get("type") in ("Error", "Fatal"):
                    raise HttpError(f"Flux TTS error: {str(d)[:200]}")
        finally:
            if not done and self.ws is not None:
                try:
                    await self.interrupt()
                except Exception:
                    self.ws = None


_FLUX = {}


async def flux_audio(client, text, sid, model):
    session = _FLUX.setdefault(model, FluxSession(model))
    async with aclosing(session.speak(text)) as inner:    # so an early stop reaches the Interrupt in speak()
        async for c in inner:
            yield c


ENGINES = {
    # name: (label, key variable, generator, model, audio format, speaks Hindi)
    "el_flash": ("ElevenLabs Flash v2.5", "ELEVENLABS_API_KEY", el_audio, "eleven_flash_v2_5", "pcm24", True),
    "el_multi": ("ElevenLabs Multilingual v2", "ELEVENLABS_API_KEY", el_audio, "eleven_multilingual_v2", "pcm24", True),
    "dg_aura2": ("Deepgram Aura-2 (Thalia)", "DEEPGRAM_API_KEY", dg_audio, "aura-2-thalia-en", "pcm24", False),
    "dg_phoebe": ("Deepgram Aura-2 (Phoebe)", "DEEPGRAM_API_KEY", dg_audio, "aura-2-phoebe-en", "pcm24", False),
    "dg_flux": ("Deepgram Flux TTS (Haley)", "DEEPGRAM_API_KEY", flux_audio, "flux-haley-en", "pcm24", False),
    "sarvam": ("Sarvam Bulbul v3 (full file)", "SARVAM_API_KEY", sarvam_rest_audio, "bulbul:v3", "wav", True),
    "sarvam_stream": ("Sarvam Bulbul v3 (streaming MP3)", "SARVAM_API_KEY", sarvam_stream_audio, "bulbul:v3", "mp3", True),
    "groq": ("Groq Orpheus (hannah)", "GROQ_API_KEY", groq_audio, "canopylabs/orpheus-v1-english", "wav", False),
}
SAVE_IN_LISTENING_TEST = ("el_flash", "el_multi", "dg_aura2", "dg_phoebe", "dg_flux", "sarvam", "groq")


def have_key(name: str) -> bool:
    v = os.getenv(name, "")
    return bool(v) and not v.startswith("your_")


def decode(buf: bytes, fmt: str):
    """-> (pcm16 bytes, sample rate) or (None, None) when the format is not saved (MP3)."""
    if fmt == "pcm24":
        return buf, 24000
    if fmt == "wav":
        with wave.open(io.BytesIO(buf)) as w:
            return w.readframes(w.getnframes()), w.getframerate()
    return None, None


async def one_request(client, eng: str, sid: str):
    label, _, gen, model, fmt, _ = ENGINES[eng]
    text = SENTENCES[sid]
    t0 = time.perf_counter()
    first, buf = None, bytearray()
    async with aclosing(gen(client, text, sid, model)) as g:
        async for chunk in g:
            buf += chunk
            if first is None and len(buf) >= (1000 if fmt == "mp3" else MIN_BYTES_FOR_FIRST_AUDIO):
                first = (time.perf_counter() - t0) * 1000
    total = (time.perf_counter() - t0) * 1000
    pcm, sr = decode(bytes(buf), fmt)
    return {"ttfa_ms": first if first is not None else total, "total_ms": total,
            "audio_s": len(pcm) / (sr * 2) if pcm else None, "pcm": pcm, "sr": sr, "chars": len(text)}


def save_wav(path: Path, pcm: bytes, sr: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm)


async def interruption_test(client, eng: str) -> dict:
    """Start the longest sentence, stop after ~0.5 s of audio, and time the cancel."""
    label, _, gen, model, fmt, _ = ENGINES[eng]
    need = 24000 if fmt == "pcm24" else 8000     # ~0.5 s of PCM; about as many bytes of MP3/WAV
    got, t0 = 0, time.perf_counter()
    g = gen(client, SENTENCES["s6"], "s6", model)
    async for chunk in g:
        got += len(chunk)
        if got >= need:
            break
    t_stop = time.perf_counter()
    await g.aclose()
    cancel_ms = (time.perf_counter() - t_stop) * 1000
    nxt = await one_request(client, eng, "s1")
    session = _FLUX.get(model)
    return {"cancel_ms": round(cancel_ms, 1), "server_confirmed_interrupt": bool(session and session.interrupt_ms),
            "after_cancel_next_ttfa_ms": round(nxt["ttfa_ms"]),
            "bytes_when_stopped": got, "stopped_at_ms": round((t_stop - t0) * 1000)}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default=",".join(ENGINES))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--only", help="comma list of sentence ids, e.g. s1,s2")
    ap.add_argument("--no-interrupt", action="store_true")
    args = ap.parse_args()
    sentences = [s for s in SENTENCES if not args.only or s in args.only.split(",")]
    results = {}
    async with httpx.AsyncClient(timeout=60, http2=False) as client:
        for eng in args.engines.split(","):
            label, key_var, _, _, fmt, hindi = ENGINES[eng]
            if not have_key(key_var):
                print(f"SKIP {eng}: {key_var} is not set in .env")
                continue
            runs, errors, first_call = [], [], None
            for sid in sentences:
                if sid in HINGLISH and not hindi:
                    continue
                for rep in range(args.repeats):
                    try:
                        r = await one_request(client, eng, sid)
                    except Exception as e:
                        errors.append(f"{sid}: {str(e)[:260]}")
                        break
                    if first_call is None:
                        first_call = r["ttfa_ms"]
                    if rep == 0 and eng in SAVE_IN_LISTENING_TEST and r["pcm"]:
                        save_wav(AUDIO / f"{eng}__{sid}.wav", r["pcm"], r["sr"])
                    runs.append({"sid": sid, **{k: v for k, v in r.items() if k != "pcm"}})
            en = [r for r in runs if r["sid"] not in HINGLISH]
            summary = {"label": label, "requests": len(runs), "errors": errors[:3], "first_call_ttfa_ms": round(first_call) if first_call else None}
            if en:
                ttfa = [r["ttfa_ms"] for r in en]
                tot = [r["total_ms"] for r in en]
                rtf = [r["total_ms"] / 1000 / r["audio_s"] for r in en if r["audio_s"]]
                summary.update({"ttfa_ms_median": round(statistics.median(ttfa)), "ttfa_ms_max": round(max(ttfa)),
                                "total_ms_median": round(statistics.median(tot)),
                                "rtf_median": round(statistics.median(rtf), 2) if rtf else None})
            hi = [r for r in runs if r["sid"] in HINGLISH]
            if hi:
                summary["hinglish_ttfa_ms_median"] = round(statistics.median(r["ttfa_ms"] for r in hi))
            if not args.no_interrupt and en:
                try:
                    summary["interrupt"] = await interruption_test(client, eng)
                except Exception as e:
                    summary["interrupt"] = {"error": str(e)[:200]}
            results[eng] = {"summary": summary, "runs": runs}
            print(f"{label:<34} first call {summary['first_call_ttfa_ms']} ms | median first audio {summary.get('ttfa_ms_median')} ms "
                  f"(max {summary.get('ttfa_ms_max')}) | whole sentence {summary.get('total_ms_median')} ms | "
                  f"real-time factor {summary.get('rtf_median')} | cancel {summary.get('interrupt', {}).get('cancel_ms')} ms"
                  + (f" | ERRORS: {errors[0]}" if errors else ""), flush=True)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "tts_bench.json"
    merged = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    merged.update({k: v for k, v in results.items() if v["runs"]})    # keep other engines; skip engines that produced nothing
    out.write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
