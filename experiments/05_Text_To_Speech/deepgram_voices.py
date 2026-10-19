"""Hear one sentence in every English Deepgram Aura-2 voice.

  python deepgram_voices.py                      # sentence s5, all voices, then open data/voices/index.html
  python deepgram_voices.py --sentence s2

Makes data/voices/<voice>.wav and an index.html with a play button, gender, accent and style for each voice.
A real API call per voice (about 70 characters each, well under a cent).
"""
import argparse
import asyncio
import html
import json
import os
import sys
import wave
from pathlib import Path

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent / ".env")
sys.path.insert(0, str(HERE))
from tts_bench import SENTENCES  # noqa: E402

OUT = HERE / "data" / "voices"
# Flux TTS has no public voice list in the API; these names were accepted by the account (others tried were refused).
FLUX_VOICES = ["haley", "heather", "alexis", "nora", "hannah", "cole", "jack", "luke"]


async def flux_voice(name: str, text: str, key: str) -> bytes:
    from websockets.asyncio.client import connect
    audio = bytearray()
    async with connect(f"wss://api.deepgram.com/v2/speak?model=flux-{name}-en&encoding=linear16&sample_rate=24000",
                       additional_headers={"Authorization": f"Token {key}"}, max_size=None) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "Speak", "text": text}))
        await ws.send(json.dumps({"type": "Flush"}))
        while True:
            m = await asyncio.wait_for(ws.recv(), 20)
            if isinstance(m, bytes):
                audio += m
            elif json.loads(m).get("type") == "SpeechMetadata":
                break
        await ws.send(json.dumps({"type": "Close"}))
    return bytes(audio)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sentence", default="s5")
    args = ap.parse_args()
    text = SENTENCES[args.sentence]
    key = os.getenv("DEEPGRAM_API_KEY")
    auth = {"Authorization": f"Token {key}"}
    OUT.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=60) as client:
        models = (await client.get("https://api.deepgram.com/v1/models", headers=auth)).json()["tts"]
        voices = [m for m in models if m["canonical_name"].startswith("aura-2-") and m["canonical_name"].endswith("-en")]
        rows = []
        for m in voices:
            name = m["canonical_name"]
            r = await client.post(f"https://api.deepgram.com/v1/speak?model={name}&encoding=linear16&sample_rate=24000&container=none",
                                  headers=auth, json={"text": text})
            if r.status_code >= 400:
                print(f"  {name}: HTTP {r.status_code} {r.text[:120]}")
                continue
            short = name.replace("aura-2-", "").replace("-en", "")
            with wave.open(str(OUT / f"{short}.wav"), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(r.content)
            md = m.get("metadata", {})
            tags = md.get("tags", [])
            gender = "female" if "feminine" in tags else "male" if "masculine" in tags else "?"
            rows.append({"voice": short, "model": name, "gender": gender, "accent": md.get("accent", ""),
                         "style": ", ".join(t for t in tags if t not in ("feminine", "masculine"))})
            print(f"  {short:<10} {gender:<7} {md.get('accent', ''):<11} {rows[-1]['style']}", flush=True)

    for name in FLUX_VOICES:
        try:
            pcm = await flux_voice(name, text, key)
        except Exception as e:
            print(f"  flux-{name}: {str(e)[:100]}")
            continue
        with wave.open(str(OUT / f"flux_{name}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
        rows.append({"voice": f"flux_{name}", "model": f"flux-{name}-en", "gender": "? (Flux, newer model)",
                     "accent": "", "style": "Deepgram Flux TTS"})
        print(f"  flux_{name:<8} {len(pcm) / 48000:.1f} s", flush=True)

    rows.sort(key=lambda r: (not r["voice"].startswith("flux_"), r["gender"], r["accent"], r["voice"]))
    cells = "\n".join(
        f"<tr><td><b>{html.escape(r['voice'])}</b></td><td>{r['gender']}</td><td>{html.escape(r['accent'])}</td>"
        f"<td>{html.escape(r['style'])}</td><td><audio controls preload=\"none\" src=\"{r['voice']}.wav\"></audio></td></tr>"
        for r in rows)
    (OUT / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Deepgram Aura-2 voices</title>"
        "<style>body{font-family:sans-serif;margin:24px}td,th{padding:6px 12px;text-align:left}tr:nth-child(even){background:#f3f3f3}</style>"
        f"<h2>Deepgram Aura-2 English voices</h2><p>\"{html.escape(text)}\"</p>"
        f"<table><tr><th>Voice</th><th>Gender</th><th>Accent</th><th>Style</th><th>Play</th></tr>{cells}</table>",
        encoding="utf-8")
    (OUT / "voices.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"\n{len(rows)} voices saved. Open {OUT / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
