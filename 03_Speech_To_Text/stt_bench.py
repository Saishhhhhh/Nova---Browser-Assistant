"""Speech-to-text benchmark on your recorded commands (run prepare_dataset.py first).

  python stt_bench.py batch                                   # every engine whose key is in .env
  python stt_bench.py batch --engines groq:whisper-large-v3-turbo,deepgram --boost
  python stt_bench.py stream --engines deepgram,assemblyai    # real-time streaming, measures latency
  python stt_bench.py report                                  # comparison table from results/

Engines: groq (Whisper), deepgram (Nova), assemblyai, elevenlabs (Scribe), sarvam (Saaras).
Keys come from the root .env (GROQ_API_KEY, DEEPGRAM_API_KEY, ASSEMBLYAI_API_KEY,
ELEVENLABS_API_KEY, SARVAM_API_KEY); an engine without a key is skipped.
Real API calls, but a few seconds of audio each: well under a cent per engine.

Scored per command: word error rate (WER), exact match, intent match (does the Experiment 2
command parser read the transcript the same way as the script?), key-term hits, and time.
V0 (silence) checks that no engine invents words. --boost adds a vocabulary hint with site names.
"""
import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = HERE / "data"
RESULTS = HERE / "results"
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT / "02_Reasoning_and_Routing"))
from dom_fastpath import parse_command  # noqa: E402  (the Experiment 2 command parser)

# Site and tool names the assistant would know in advance (used by --boost only).
BOOST_TERMS = ["YouTube", "GitHub", "Wikipedia", "Flipkart", "Gmail", "Reddit", "LinkedIn", "Amazon",
               "Hacker News", "Instagram", "ChatGPT", "Playwright"]
KEYTERMS = ["lg", "msi", "ultragear", "flipkart", "gmail", "reddit", "github", "youtube", "wikipedia",
            "playwright", "kubernetes", "alan turing", "toscrape", "linkedin", "amazon", "lofi", "rupees",
            "hacker news"]
COMPOUNDS = [("lo fi", "lofi"), ("ultra gear", "ultragear"), ("you tube", "youtube"), ("git hub", "github"),
             ("linked in", "linkedin"), ("g mail", "gmail"), ("play wright", "playwright")]

# ----------------------------------------------------------------------------- text scoring

ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
        "sixteen seventeen eighteen nineteen").split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def num_to_words(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    if n < 1000:
        return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + num_to_words(n % 100))
    if n < 1_000_000:
        return num_to_words(n // 1000) + " thousand" + ("" if n % 1000 == 0 else " " + num_to_words(n % 1000))
    return str(n)


def norm_text(s: str) -> str:
    """Lowercase, spell out numbers, 'books.toscrape.com' -> 'books dot toscrape dot com', drop punctuation."""
    s = (s or "").lower().replace("’", "").replace("'", "")
    s = re.sub(r"₹\s*([\d,]+)", r"\1 rupees", s)
    s = re.sub(r"\brs\.?\s*([\d,]+)", r"\1 rupees", s)
    s = re.sub(r"\brs\b\.?", " rupees ", s)
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)
    s = re.sub(r"(?<=[a-z0-9])\.(?=[a-z0-9])", " dot ", s)
    s = re.sub(r"\d+", lambda m: num_to_words(int(m.group())), s)
    s = s.replace("-", " ")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for spaced, compact in COMPOUNDS:
        s = s.replace(spaced, compact)
    return s


def edit_distance(ref: list, hyp: list) -> int:
    d = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(hyp) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (ref[i - 1] != hyp[j - 1]))
            prev = cur
    return d[len(hyp)]


def keyterm_counts(ref_n: str, hyp_n: str) -> tuple:
    def present(term: str, text_n: str) -> bool:
        if len(term) <= 3:
            return re.search(rf"\b{term}\b", text_n) is not None
        return term.replace(" ", "") in text_n.replace(" ", "")
    needed = [t for t in KEYTERMS if present(t, ref_n)]
    return sum(present(t, hyp_n) for t in needed), len(needed)


def intent_of(text_n: str) -> tuple:
    it = parse_command(text_n)
    if it.kind == "unknown":  # no rule reads it: the whole sentence is what the model step will see
        return ("unknown", text_n)
    return (it.kind, norm_text(it.text), norm_text(it.target), it.direction, it.amount)


def score(clip: dict, hyp: str) -> dict:
    ref_n, hyp_n = norm_text(clip["text"]), norm_text(hyp)
    hit, need = keyterm_counts(ref_n, hyp_n)
    return {
        "text": hyp, "ref": clip["text"], "edits": edit_distance(ref_n.split(), hyp_n.split()),
        "ref_words": len(ref_n.split()), "exact": ref_n == hyp_n,
        "intent": intent_of(ref_n) == intent_of(hyp_n), "kt_hit": hit, "kt_need": need,
    }


# ----------------------------------------------------------------------------- batch engines

def check(r: httpx.Response) -> httpx.Response:
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r


async def groq_batch(client, key, wav, vid, model, boost):
    data = {"model": model or "whisper-large-v3-turbo", "temperature": "0", "response_format": "json"}
    if vid != "V10":
        data["language"] = "en"
    if boost:
        data["prompt"] = "Voice commands for a web browser. Names: " + ", ".join(BOOST_TERMS) + "."
    r = await client.post("https://api.groq.com/openai/v1/audio/transcriptions",
                          headers={"Authorization": f"Bearer {key}"}, data=data,
                          files={"file": ("clip.wav", wav, "audio/wav")})
    return check(r).json()["text"]


async def deepgram_batch(client, key, wav, vid, model, boost):
    params = [("model", model or "nova-3"), ("smart_format", "true"), ("language", "multi" if vid == "V10" else "en")]
    if boost:
        params += [("keyterm", t) for t in BOOST_TERMS]
    r = await client.post("https://api.deepgram.com/v1/listen", params=params, content=wav,
                          headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"})
    return check(r).json()["results"]["channels"][0]["alternatives"][0]["transcript"]


async def assemblyai_batch(client, key, wav, vid, model, boost):
    h = {"authorization": key}
    up = check(await client.post("https://api.assemblyai.com/v2/upload", headers=h, content=wav)).json()
    body = {"audio_url": up["upload_url"]}
    if vid == "V10":
        body["language_detection"] = True
    else:
        body["language_code"] = "en"
    if model:  # the old single speech_model field is rejected; the API wants a priority list
        body["speech_models"] = [model] if model == "universal-2" else [model, "universal-2"]
    if boost:
        body["keyterms_prompt"] = BOOST_TERMS
    tid = check(await client.post("https://api.assemblyai.com/v2/transcript", headers=h, json=body)).json()["id"]
    while True:
        g = check(await client.get(f"https://api.assemblyai.com/v2/transcript/{tid}", headers=h)).json()
        if g["status"] == "completed":
            return g.get("text") or ""
        if g["status"] == "error":
            raise RuntimeError(f"assemblyai error: {g.get('error')}")
        await asyncio.sleep(0.25)


async def elevenlabs_batch(client, key, wav, vid, model, boost):
    data = {"model_id": model or "scribe_v2", "tag_audio_events": "false", "diarize": "false"}
    if vid != "V10":
        data["language_code"] = "en"
    if boost:
        data["keyterms"] = BOOST_TERMS  # httpx repeats the field once per list item
    r = await client.post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": key},
                          data=data, files={"file": ("clip.wav", wav, "audio/wav")})
    return check(r).json()["text"]


async def sarvam_batch(client, key, wav, vid, model, boost):
    data = {"language_code": "unknown" if vid == "V10" else "en-IN"}
    if model:
        data["model"] = model
    r = await client.post("https://api.sarvam.ai/speech-to-text", headers={"api-subscription-key": key},
                          data=data, files={"file": ("clip.wav", wav, "audio/wav")})
    return check(r).json()["transcript"]


ENGINES = {
    "groq": ("GROQ_API_KEY", groq_batch),
    "deepgram": ("DEEPGRAM_API_KEY", deepgram_batch),
    "assemblyai": ("ASSEMBLYAI_API_KEY", assemblyai_batch),
    "elevenlabs": ("ELEVENLABS_API_KEY", elevenlabs_batch),
    "sarvam": ("SARVAM_API_KEY", sarvam_batch),
}
DEFAULT_BATCH = "groq:whisper-large-v3-turbo,groq:whisper-large-v3,deepgram,assemblyai,elevenlabs,sarvam"
MIN_INTERVAL = {"groq": 3.2}  # seconds between requests: Groq's free tier allows 20 Whisper requests/minute


async def timed_call(fn, *args):
    """Call an engine; retry on rate limits (HTTP 429). Returns (text, ms of the successful attempt only)."""
    for attempt in range(4):
        t = time.perf_counter()
        try:
            return await fn(*args), (time.perf_counter() - t) * 1000
        except RuntimeError as e:
            if "HTTP 429" in str(e) and attempt < 3:
                await asyncio.sleep(6 * (attempt + 1))
                continue
            raise

# ----------------------------------------------------------------------------- streaming engines

async def pace_audio(ws, pcm: bytes) -> float:
    """Send 16 kHz 16-bit mono audio in 100 ms chunks at real-time speed; returns the start time."""
    chunk = 3200
    t0 = time.perf_counter()
    for i in range(0, len(pcm), chunk):
        await ws.send(pcm[i:i + chunk])
        await asyncio.sleep(max(0.0, t0 + (i + chunk) / 32000 - time.perf_counter()))
    return t0


async def deepgram_stream(key, clip, pcm):
    from websockets.asyncio.client import connect
    q = urlencode({"model": "nova-3", "encoding": "linear16", "sample_rate": 16000, "channels": 1,
                   "interim_results": "true", "endpointing": 300, "smart_format": "true",
                   "language": "multi" if clip["source"] == "V10" else "en"})
    msgs = []
    async with connect(f"wss://api.deepgram.com/v1/listen?{q}", additional_headers={"Authorization": f"Token {key}"},
                       max_size=None) as ws:
        async def receiver():
            async for raw in ws:
                if isinstance(raw, str):
                    msgs.append((time.perf_counter(), json.loads(raw)))
        recv = asyncio.create_task(receiver())
        t0 = await pace_audio(ws, pcm + b"\x00" * 64000)  # + 2 s of silence so endpointing can fire
        await ws.send(json.dumps({"type": "CloseStream"}))
        try:
            await asyncio.wait_for(recv, 3)
        except Exception:
            recv.cancel()
    start_abs, end_abs = t0 + clip["speech_start_s"], t0 + clip["speech_end_s"]
    text_parts, first_partial, final_ms = [], None, None
    for t, m in msgs:
        if m.get("type") != "Results":
            continue
        tr = m["channel"]["alternatives"][0]["transcript"]
        if tr and first_partial is None:
            first_partial = (t - start_abs) * 1000
        if m.get("is_final") and tr:
            text_parts.append(tr)
        if m.get("speech_final") and final_ms is None and text_parts:
            final_ms = (t - end_abs) * 1000
            break
    return " ".join(text_parts), first_partial, final_ms


async def assemblyai_stream(key, clip, pcm):
    from websockets.asyncio.client import connect
    q = urlencode({"sample_rate": 16000, "format_turns": "true"})
    msgs = []
    async with connect(f"wss://streaming.assemblyai.com/v3/ws?{q}", additional_headers={"Authorization": key},
                       max_size=None) as ws:
        async def receiver():
            async for raw in ws:
                if isinstance(raw, str):
                    msgs.append((time.perf_counter(), json.loads(raw)))
        recv = asyncio.create_task(receiver())
        for _ in range(100):  # wait for the session to open
            if any(m.get("type") == "Begin" for _, m in msgs):
                break
            await asyncio.sleep(0.05)
        t0 = await pace_audio(ws, pcm + b"\x00" * 64000)
        await asyncio.sleep(0.6)  # let a formatted version of the final turn arrive
        await ws.send(json.dumps({"type": "Terminate"}))
        try:
            await asyncio.wait_for(recv, 3)
        except Exception:
            recv.cancel()
    start_abs, end_abs = t0 + clip["speech_start_s"], t0 + clip["speech_end_s"]
    text, first_partial, final_ms = "", None, None
    for t, m in msgs:
        if m.get("type") != "Turn":
            continue
        tr = m.get("transcript") or ""
        if tr and first_partial is None:
            first_partial = (t - start_abs) * 1000
        if m.get("end_of_turn") and tr:
            if final_ms is None:
                final_ms = (t - end_abs) * 1000
            text = tr
    return text, first_partial, final_ms


async def deepgram_flux_stream(key, clip, pcm):
    """Deepgram Flux: /v2/listen, the model decides end-of-turn itself (EndOfTurn event)."""
    from websockets.asyncio.client import connect
    q = urlencode({"model": "flux-general-en", "encoding": "linear16", "sample_rate": 16000})
    msgs = []
    async with connect(f"wss://api.deepgram.com/v2/listen?{q}", additional_headers={"Authorization": f"Token {key}"},
                       max_size=None) as ws:
        async def receiver():
            async for raw in ws:
                if isinstance(raw, str):
                    msgs.append((time.perf_counter(), json.loads(raw)))
        recv = asyncio.create_task(receiver())
        t0 = await pace_audio(ws, pcm + b"\x00" * 64000)
        await ws.send(json.dumps({"type": "CloseStream"}))
        try:
            await asyncio.wait_for(recv, 3)
        except Exception:
            recv.cancel()
    start_abs, end_abs = t0 + clip["speech_start_s"], t0 + clip["speech_end_s"]
    text, first_partial, final_ms = "", None, None
    for t, m in msgs:
        if m.get("type") != "TurnInfo":
            continue
        tr = m.get("transcript") or ""
        if tr and first_partial is None:
            first_partial = (t - start_abs) * 1000
        if m.get("event") == "EndOfTurn" and tr and final_ms is None:
            final_ms = (t - end_abs) * 1000
            text = tr
    return text, first_partial, final_ms


async def elevenlabs_rt_stream(key, clip, pcm):
    """ElevenLabs Scribe v2 Realtime with server-side VAD commit after 0.5 s of silence."""
    import base64
    from websockets.asyncio.client import connect
    q = urlencode({"model_id": "scribe_v2_realtime", "audio_format": "pcm_16000", "commit_strategy": "vad",
                   "vad_silence_threshold_secs": 0.5,
                   "language_code": "en" if clip["source"] != "V10" else ""})
    msgs = []
    async with connect(f"wss://api.elevenlabs.io/v1/speech-to-text/realtime?{q}",
                       additional_headers={"xi-api-key": key}, max_size=None) as ws:
        async def receiver():
            async for raw in ws:
                msgs.append((time.perf_counter(), json.loads(raw)))
        recv = asyncio.create_task(receiver())
        chunk, data = 3200, pcm + b"\x00" * 64000
        t0 = time.perf_counter()
        for i in range(0, len(data), chunk):
            await ws.send(json.dumps({"message_type": "input_audio_chunk", "sample_rate": 16000, "commit": False,
                                      "audio_base_64": base64.b64encode(data[i:i + chunk]).decode()}))
            await asyncio.sleep(max(0.0, t0 + (i + chunk) / 32000 - time.perf_counter()))
        await asyncio.sleep(0.5)
        recv.cancel()
    start_abs, end_abs = t0 + clip["speech_start_s"], t0 + clip["speech_end_s"]
    parts, first_partial, final_ms = [], None, None
    for t, m in msgs:
        kind, tr = m.get("message_type"), m.get("text") or ""
        if kind in ("partial_transcript", "committed_transcript", "committed_transcript_with_timestamps") and tr:
            if first_partial is None:
                first_partial = (t - start_abs) * 1000
        if kind == "committed_transcript" and tr:
            parts.append(tr)
            if final_ms is None:
                final_ms = (t - end_abs) * 1000
    return " ".join(parts), first_partial, final_ms


def with_retry(fn):
    """Streaming sessions sometimes get dropped (policy violation / 1008); try again once after a pause."""
    async def wrapped(key, clip, pcm):
        try:
            return await fn(key, clip, pcm)
        except Exception:
            await asyncio.sleep(2)
            return await fn(key, clip, pcm)
    return wrapped


STREAMERS = {"deepgram": ("DEEPGRAM_API_KEY", deepgram_stream), "assemblyai": ("ASSEMBLYAI_API_KEY", assemblyai_stream),
             "deepgram_flux": ("DEEPGRAM_API_KEY", deepgram_flux_stream),
             "elevenlabs_rt": ("ELEVENLABS_API_KEY", elevenlabs_rt_stream)}

# ----------------------------------------------------------------------------- runners

def have_key(env_name: str) -> bool:
    v = os.getenv(env_name, "")
    return bool(v) and not v.startswith("your_")


def summarize(rows: list) -> dict:
    clips = [r for r in rows if r["kind"] == "clip" and not r.get("error")]
    errors = [r for r in rows if r["kind"] == "clip" and r.get("error")]
    sil = [r for r in rows if r["kind"] == "silence"]
    core = [r for r in clips if r["id"].split("_")[0] != "V10"]  # Hinglish is scored separately
    words = sum(r["ref_words"] for r in core) or 1
    ms = [r["ms"] for r in core]
    kt_need = sum(r["kt_need"] for r in core) or 1
    s = {
        "clips_scored": len(core), "errors": len(errors),
        "wer_pct": round(100 * sum(r["edits"] for r in core) / words, 1),
        "exact_pct": round(100 * sum(r["exact"] for r in core) / max(len(core), 1)),
        "intent_pct": round(100 * sum(r["intent"] for r in core) / max(len(core), 1)),
        "keyterm_pct": round(100 * sum(r["kt_hit"] for r in core) / kt_need),
        "ms_median": round(statistics.median(ms)) if ms else None,
        "ms_max": round(max(ms)) if ms else None,
        "silence_hallucinated": [r["text"] for r in sil if r.get("hallucinated")],
        "silence_checked": bool(sil),
    }
    if any("first_partial_ms" in r for r in core):
        fin = [r["final_ms"] for r in core if r.get("final_ms") is not None]
        first = [r["first_partial_ms"] for r in core if r.get("first_partial_ms") is not None]
        s["final_after_speech_end_ms_median"] = round(statistics.median(fin)) if fin else None
        s["final_after_speech_end_ms_max"] = round(max(fin)) if fin else None
        s["first_partial_after_speech_start_ms_median"] = round(statistics.median(first)) if first else None
        s["no_final_count"] = sum(r.get("final_ms") is None for r in core)
    hinglish = [r for r in clips if r["id"].split("_")[0] == "V10"]
    if hinglish:
        s["hinglish_texts"] = [r["text"] for r in hinglish]
    return s


def save(name: str, mode: str, rows: list) -> None:
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"stt_{mode}_{re.sub(r'[^A-Za-z0-9._+-]+', '_', name)}.json"
    out.write_text(json.dumps({"engine": name, "mode": mode, "summary": summarize(rows), "rows": rows},
                              indent=1, ensure_ascii=False), encoding="utf-8")


def only_filter(manifest: list, only: str | None, limit: int | None) -> list:
    if only:
        wanted = {v.strip().upper() for v in only.split(",")}
        manifest = [c for c in manifest if c["source"] in wanted]
    return manifest[:limit] if limit else manifest


async def run_batch(args) -> None:
    manifest = only_filter(json.loads((DATA / "manifest.json").read_text(encoding="utf-8")), args.only, args.limit)
    silence = DATA / "wav" / "V0.wav"
    for spec in args.engines.split(","):
        base, _, model = spec.strip().partition(":")
        env_name, fn = ENGINES[base]
        if not have_key(env_name):
            print(f"SKIP {spec}: {env_name} is not set in .env")
            continue
        for boost in ([False, True] if args.boost else [False]):
            name = spec + ("+boost" if boost else "")
            rows = []
            last_start = 0.0

            async def pace():
                nonlocal last_start
                wait = MIN_INTERVAL.get(base, 0.0) - (time.perf_counter() - last_start)
                if wait > 0:
                    await asyncio.sleep(wait)
                last_start = time.perf_counter()

            async with httpx.AsyncClient(timeout=60) as client:
                for clip in manifest:
                    wav = (HERE / clip["file"]).read_bytes()
                    await pace()
                    try:
                        hyp, ms = await timed_call(fn, client, os.getenv(env_name), wav, clip["source"], model or None, boost)
                        row = {"kind": "clip", "id": clip["id"], **score(clip, hyp), "ms": ms}
                    except Exception as e:
                        row = {"kind": "clip", "id": clip["id"], "error": str(e)[:200], "ms": 0}
                    rows.append(row)
                if silence.exists() and not args.only:
                    await pace()
                    try:
                        hyp, ms = await timed_call(fn, client, os.getenv(env_name), silence.read_bytes(), "V0",
                                                   model or None, boost)
                        rows.append({"kind": "silence", "id": "V0", "text": hyp, "hallucinated": bool(norm_text(hyp)),
                                     "ms": ms})
                    except Exception as e:
                        rows.append({"kind": "silence", "id": "V0", "text": "", "hallucinated": False,
                                     "error": str(e)[:200], "ms": 0})
            save(name, "batch", rows)
            s = summarize(rows)
            print(f"{name:<38} WER {s['wer_pct']:>5}%  intent {s['intent_pct']:>3}%  keyterms {s['keyterm_pct']:>3}%  "
                  f"median {s['ms_median']} ms  errors {s['errors']}  silence-words {len(s['silence_hallucinated'])}")
            first_err = next((r["error"] for r in rows if r.get("error")), None)
            if first_err:
                print(f"    first error: {first_err}")


async def run_stream(args) -> None:
    manifest = only_filter(json.loads((DATA / "manifest.json").read_text(encoding="utf-8")), args.only, args.limit)
    for spec in args.engines.split(","):
        env_name, fn = STREAMERS[spec.strip()]
        if not have_key(env_name):
            print(f"SKIP {spec}: {env_name} is not set in .env")
            continue
        fn = with_retry(fn)
        rows = []
        for clip in manifest:
            _, pcm = wavfile.read(HERE / clip["file"])
            t = time.perf_counter()
            try:
                hyp, first, final = await fn(os.getenv(env_name), clip, pcm.tobytes())
                row = {"kind": "clip", "id": clip["id"], **score(clip, hyp), "first_partial_ms": first, "final_ms": final}
            except Exception as e:
                row = {"kind": "clip", "id": clip["id"], "error": f"{type(e).__name__}: {e}"[:200]}
            row["ms"] = (time.perf_counter() - t) * 1000
            rows.append(row)
        save(spec.strip(), "stream", rows)
        s = summarize(rows)
        print(f"{spec:<14} WER {s['wer_pct']:>5}%  intent {s['intent_pct']:>3}%  "
              f"final after speech end: median {s.get('final_after_speech_end_ms_median')} ms, "
              f"max {s.get('final_after_speech_end_ms_max')} ms  first partial: "
              f"{s.get('first_partial_after_speech_start_ms_median')} ms  errors {s['errors']}")
        first_err = next((r["error"] for r in rows if r.get("error")), None)
        if first_err:
            print(f"    first error: {first_err}")


def rescore() -> None:
    """Recompute every metric from the saved transcripts (no API calls) after changing the scoring rules."""
    manifest = {c["id"]: c for c in json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))}
    for f in sorted(RESULTS.glob("stt_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for r in d["rows"]:
            if r["kind"] == "clip" and not r.get("error"):
                r.update(score(manifest[r["id"]], r["text"]))
            elif r["kind"] == "silence" and not r.get("error"):
                r["hallucinated"] = bool(norm_text(r["text"]))
        d["summary"] = summarize(d["rows"])
        f.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"rescored {f.name}")


def report() -> None:
    files = sorted(RESULTS.glob("stt_*.json"))
    if not files:
        print("no results yet")
        return
    lines = ["| Engine | Mode | WER | Exact | Intent | Key terms | Median (ms) | Slowest (ms) | Silence words | Errors |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    entries = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    entries.sort(key=lambda e: e["summary"]["wer_pct"])
    for e in entries:
        s = e["summary"]
        lat = (s.get("final_after_speech_end_ms_median"), s.get("final_after_speech_end_ms_max")) \
            if e["mode"] == "stream" else (s["ms_median"], s["ms_max"])
        sil = len(s["silence_hallucinated"]) if s["silence_checked"] else "n/a"
        lines.append(f"| {e['engine']} | {e['mode']} | {s['wer_pct']}% | {s['exact_pct']}% | {s['intent_pct']}% | "
                     f"{s['keyterm_pct']}% | {lat[0]} | {lat[1]} | {sil} | {s['errors']} |")
    lines.append("")
    lines.append("Batch latency = time to upload one clip and get the transcript back. Stream latency = time from "
                 "the end of speech to the final transcript, with audio sent at real-time speed.")
    table = "\n".join(lines)
    (RESULTS / "SUMMARY.md").write_text("# Speech-to-text results\n\n" + table + "\n", encoding="utf-8")
    print(table)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, default in (("batch", DEFAULT_BATCH), ("stream", "deepgram,assemblyai")):
        p = sub.add_parser(name)
        p.add_argument("--engines", default=default)
        p.add_argument("--only", help="comma list of recordings, e.g. V3,V6")
        p.add_argument("--limit", type=int)
        if name == "batch":
            p.add_argument("--boost", action="store_true", help="also run each engine with a vocabulary hint")
    sub.add_parser("report")
    sub.add_parser("rescore")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.cmd == "report":
        report()
    elif a.cmd == "rescore":
        rescore()
    else:
        asyncio.run(run_batch(a) if a.cmd == "batch" else run_stream(a))
