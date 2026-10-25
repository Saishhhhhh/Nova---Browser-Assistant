"""Reproduces a live bug: a short "Hey Jarvis, open github" utterance was rejected because the wake
detector needs a little trailing audio to recognise the word, and VAD had already decided the utterance
was over by then. Confirms the catch-up window (jarvis/voice.py's run()) accepts it anyway, using the exact
same run() code path real voice input goes through - not a separate simulation.

  python -m tests.test_wake_race        # real browser + real Deepgram TTS synth, a few cents
"""
import argparse
import io
import os
import sys
import time
import wave

import httpx
import numpy as np
from browser_use import Browser

from jarvis import app, config
from jarvis.dom_fastpath import make_picker_from_env
from jarvis.router import CommandRouter


def synth_pcm_16k(text: str) -> np.ndarray:
    r = httpx.post("https://api.deepgram.com/v1/speak?model=aura-2-phoebe-en&encoding=linear16&sample_rate=16000&container=wav",
                   headers={"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}"}, json={"text": text})
    r.raise_for_status()
    with wave.open(io.BytesIO(r.content), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def chunked_source(pcm: np.ndarray, chunk: int = 512):
    """Yields exactly like a real mic stream (sounddevice's RawInputStream, blocksize=512)."""
    for i in range(0, len(pcm), chunk):
        yield pcm[i:i + chunk]
    silence = np.zeros(chunk, dtype=np.int16)
    for _ in range(50):   # ~1.6 s of trailing silence so VAD's hangover can close the utterance
        yield silence
    yield None


def main() -> int:
    args = argparse.Namespace(text=False, script=None, no_sound=True, input_device=None, output_device=None,
                              hangover=0.5, min_speech=0.25, cue="none", idle=0, hinglish=False,
                              agent_steps=8, agent_timeout=120.0, start_url="", simulate=True, memory=True,
                              stt="elevenlabs", save_clips=False, wake_word=True)
    runner = app.AsyncRunner()
    loop = app.AppLoop(args, runner)
    # Headless Chromium, not Brave: args.text=False here only to exercise the wake-gate path (which checks
    # args.text/args.script, nothing to do with which browser backend runs), not to actually need Brave.
    browser = Browser(headless=True, no_viewport=True, keep_alive=True)
    runner.run(browser.start())
    loop.router = CommandRouter(browser, picker=make_picker_from_env(),
                                agent_llm=config.get_browser_use_llm("cerebras"),
                                agent_max_steps=args.agent_steps, agent_timeout=args.agent_timeout,
                                on_agent_start=loop.on_agent_start)
    loop.plan_client = runner.run(app._make_async_client())

    pcm = synth_pcm_16k("Hey Jarvis, open GitHub.")
    print(f"synthesized clip: {len(pcm) / 16000:.2f} s", flush=True)

    loop.run(chunked_source(pcm))
    deadline = time.perf_counter() + 20
    while loop.busy and time.perf_counter() < deadline:
        time.sleep(0.05)

    print(f"\nRESULT: {len(loop.records)} record(s)")
    for r in loop.records:
        print(f"  tier={r['tier']} ok={r['ok']} command={r['command']!r} reply={r['reply']!r}")
    ok = len(loop.records) >= 1 and loop.records[0]["ok"]
    print("PASS: the wake word was recognised and the command ran" if ok
          else "FAIL: the command was rejected (not addressed) or never ran")
    try:
        runner.run(loop.plan_client.aclose(), timeout=5)
    except Exception:
        pass
    try:
        runner.run(browser.kill(), timeout=15)
    except Exception:
        pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
