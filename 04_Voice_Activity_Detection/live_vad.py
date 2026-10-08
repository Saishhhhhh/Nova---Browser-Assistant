"""Try the VADs on your live microphone.

  python live_vad.py                          # Silero + WebRTC + Energy side by side, no API calls
  python live_vad.py --transcribe elevenlabs  # also send each finished command to ElevenLabs (a fraction of a cent each)
  python live_vad.py --list-devices
  python live_vad.py --vad silero --hangover 0.4 --transcribe sarvam --hinglish

Speak a command, then stop. The first detector in --vad is the one that cuts the clip and (with --transcribe)
sends it. Every detector prints its own START / END lines so you can see who reacts when, and the status line
shows what each one thinks right now. Press Ctrl+C to stop. Everything you say is also saved to live_out/
(gitignored): one WAV per command and the whole session, so it can be re-scored later.

Reading the numbers (printed after each command):
  silence wait   = how long the VAD waited before declaring that you finished (the hangover plus the VAD's own lag)
  transcript     = how long the speech-to-text engine took
  you waited     = silence wait + transcript, i.e. roughly how long after you stopped talking the text appeared
"""
import argparse
import asyncio
import datetime
import io
import os
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "03_Speech_To_Text"))
from vad_core import SR, Endpointer, make_detector  # noqa: E402

PRE_ROLL_S = 0.3
OUT = HERE / "live_out"


def wav_bytes(pcm: np.ndarray) -> bytes:
    buf = io.BytesIO()
    wavfile.write(buf, SR, pcm)
    return buf.getvalue()


def transcribe(engine: str, pcm: np.ndarray, hinglish: bool, tag: str, silence_wait_ms: float, lock) -> None:
    import httpx
    import stt_bench as stt

    async def run():
        env, fn = stt.ENGINES[engine]
        async with httpx.AsyncClient(timeout=60) as client:
            t = time.perf_counter()
            text = await fn(client, os.getenv(env), wav_bytes(pcm), "V10" if hinglish else "V1", None, False)
            return text, (time.perf_counter() - t) * 1000

    try:
        text, ms = asyncio.run(run())
        msg = (f"      -> \"{text}\"\n"
               f"         silence wait {silence_wait_ms:.0f} ms + transcript {ms:.0f} ms ({engine})"
               f"  =  you waited about {silence_wait_ms + ms:.0f} ms")
    except Exception as e:
        msg = f"      -> transcription failed: {str(e)[:200]}"
    with lock:
        print(f"\r{' ' * 110}\r[{tag}]\n{msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--device", help="input device number or part of its name (default: the system default)")
    ap.add_argument("--vad", default="silero,webrtc3,energy", help="comma list; the first one cuts the clips")
    ap.add_argument("--hangover", type=float, default=0.5, help="seconds of silence before declaring the end")
    ap.add_argument("--transcribe", choices=["elevenlabs", "sarvam", "groq", "deepgram", "assemblyai"])
    ap.add_argument("--hinglish", action="store_true", help="tell the engine the speech is Hinglish")
    ap.add_argument("--max-minutes", type=int, default=20)
    args = ap.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        return 0
    device = args.device
    if device is not None and device.isdigit():
        device = int(device)

    names = [n.strip() for n in args.vad.split(",") if n.strip()]
    dets = [make_detector(n) for n in names]
    eps = [Endpointer(d.frame_s, d.default_threshold, args.hangover) for d in dets]
    cursor = [0] * len(dets)
    last = [0.0] * len(dets)
    in_speech = [False] * len(dets)

    OUT.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    audio = np.zeros(SR * 60 * args.max_minutes, dtype=np.int16)
    n = 0
    q: "queue.Queue[bytes]" = queue.Queue()
    lock = threading.Lock()
    count = 0

    def callback(indata, frames, time_info, status):
        q.put(bytes(indata))

    info = sd.query_devices(device if device is not None else sd.default.device[0], "input")
    print(f"Microphone: {info['name']}")
    print(f"Detectors: {', '.join(names)}  |  hangover {args.hangover:.2f} s  |  "
          f"transcribe: {args.transcribe or 'off'}  |  saving to {OUT}")
    print("Speak a command, then stop. Ctrl+C to quit.\n", flush=True)

    t_status = 0.0
    try:
        with sd.RawInputStream(samplerate=SR, channels=1, dtype="int16", blocksize=320, device=device,
                               callback=callback):
            while n < len(audio) - 4000:
                try:
                    chunk = q.get(timeout=0.2)
                except queue.Empty:
                    continue
                x = np.frombuffer(chunk, dtype=np.int16)
                audio[n:n + len(x)] = x
                n += len(x)
                for i, (det, ep) in enumerate(zip(dets, eps)):
                    while cursor[i] + det.frame <= n:
                        frame = audio[cursor[i]:cursor[i] + det.frame]
                        cursor[i] += det.frame
                        s = det.score(frame)
                        last[i] = s
                        ev = ep.push(cursor[i] / SR, s)
                        if ev is None:
                            continue
                        if ev[0] == "start":
                            in_speech[i] = True
                            with lock:
                                print(f"\r{' ' * 110}\r  {ev[1]:7.2f}s  {names[i]:<8} START", flush=True)
                        else:
                            in_speech[i] = False
                            _, start, speech_end, trigger = ev
                            # the VAD only learns of the end `hangover` after the last speech frame; it also
                            # lags a little behind your voice, so this is the wait you actually feel
                            wait_ms = (trigger - speech_end) * 1000
                            with lock:
                                print(f"\r{' ' * 110}\r  {trigger:7.2f}s  {names[i]:<8} END    "
                                      f"speech {speech_end - start:4.2f} s, ended after {wait_ms:.0f} ms of silence",
                                      flush=True)
                            if i == 0:
                                count += 1
                                clip = audio[max(0, int((start - PRE_ROLL_S) * SR)):int(trigger * SR)].copy()
                                wavfile.write(OUT / f"{stamp}_cmd{count:02d}.wav", SR, clip)
                                if args.transcribe:
                                    threading.Thread(target=transcribe, daemon=True, args=(
                                        args.transcribe, clip, args.hinglish,
                                        f"command {count}: {len(clip) / SR:.1f} s of audio sent",
                                        wait_ms, lock)).start()
                now = time.perf_counter()
                if now - t_status > 0.1:
                    t_status = now
                    rms = np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-9
                    db = 20 * np.log10(rms / 32768)
                    parts = [f"{nm} {'SPEECH' if sp else 'quiet '}" for nm, sp in zip(names, in_speech)]
                    bar = "#" * max(0, min(20, int((db + 70) / 2.5)))
                    with lock:
                        print(f"\r  mic {db:5.0f} dB {bar:<20} | " + " | ".join(parts) + "    ", end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        if n:
            wavfile.write(OUT / f"{stamp}_session.wav", SR, audio[:n])
            print(f"\n\nSaved {count} commands and the whole session ({n / SR:.0f} s) to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
