"""Experiment 6: the bare voice loop, no browser. Use HEADPHONES.

  python voice_loop.py                       # microphone -> Silero -> Sarvam -> Phoebe, with barge-in
  python voice_loop.py --hangover 0.3        # start with a different silence wait
  python voice_loop.py --cue tick            # a short tick when it knows you finished
  python voice_loop.py --list-devices
  python voice_loop.py --simulate            # no microphone: replays recordings to test the logic (a few cents of API calls)

What happens: you speak; Silero decides when you finished; Sarvam turns it into text; a canned reply is chosen
(a short acknowledgement, or a LONG answer if you say "tell me ..." / "explain" so there is something to interrupt);
Deepgram Aura-2 Phoebe speaks it. Speak over it at any time: playback stops and you are listened to again.

Keys while it runs (no restart needed):
   1 2 3   silence wait 0.3 / 0.5 / 0.8 s          (how long it waits before deciding you finished)
   4 5 6   speech needed to interrupt 0.15 / 0.25 / 0.4 s   (also: shorter sounds are ignored)
   q       quit and print the summary
Each turn prints how long you waited. A JSON log is saved to results/turns_<time>.json.
"""
import argparse
import asyncio
import datetime
import io
import json
import os
import queue
import re
import statistics
import sys
import threading
import time
import wave
from pathlib import Path

import httpx
import numpy as np
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "04_Voice_Activity_Detection"))
from vad_core import SR, Endpointer, make_detector  # noqa: E402

VOICE = "aura-2-phoebe-en"
TTS_RATE = 24000
PRE_ROLL_S = 0.3
LONG_REPLY = ("Here is a longer answer, so you can practise interrupting me. The cheapest monitor on this page is the "
              "Acer Nitro, priced at twelve thousand four hundred and ninety-nine rupees. The next one is the MSI, at "
              "fourteen thousand, and the third is an LG UltraGear at eighteen thousand. Tell me if you want me to open any of them.")


def reply_for(text: str) -> str:
    t = re.sub(r"\s+", " ", text.strip().rstrip(".!?")).lower()
    if re.search(r"\b(tell me|explain|details?|long|read)\b", t):
        return LONG_REPLY
    if re.match(r"^scroll up", t):
        return "Scrolling up."
    if re.match(r"^scroll down", t):
        return "Scrolling down."
    if re.match(r"^(go back|back|previous page)$", t):
        return "Going back."
    m = re.match(r"^search(?: for)? (.+)$", t)
    if m:
        return f"Searching for {m.group(1)}."
    m = re.match(r"^(?:open|go to|click|press) (?:the )?(.+)$", t)
    if m:
        return f"Opening {m.group(1)}."
    return f"I heard: {text.strip()}"


# ----------------------------------------------------------------------------- audio out

class Player:
    """Plays 24 kHz mono audio in 20 ms blocks from a buffer. stop() empties the buffer, so sound ends within
    one block (plus the sound card's own buffer, reported as `device_latency_ms`)."""

    def __init__(self, device=None, simulated: bool = False):
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.played_bytes = 0
        self.stop_at = None
        self.silenced_at = None
        self.simulated = simulated
        self.device_latency_ms = 0.0
        if simulated:
            threading.Thread(target=self._sim, daemon=True).start()
        else:
            import sounddevice as sd
            self.stream = sd.RawOutputStream(samplerate=TTS_RATE, channels=1, dtype="int16", blocksize=480,
                                             latency="low", device=device, callback=self._callback)
            self.stream.start()
            self.device_latency_ms = float(self.stream.latency) * 1000

    def _pull(self, nbytes: int) -> bytes:
        with self.lock:
            chunk = bytes(self.buf[:nbytes])
            del self.buf[:nbytes]
        self.played_bytes += len(chunk)
        if self.stop_at is not None and self.silenced_at is None:
            self.silenced_at = time.perf_counter()
        return chunk + b"\x00" * (nbytes - len(chunk))

    def _callback(self, outdata, frames, time_info, status):
        outdata[:] = self._pull(frames * 2)

    def _sim(self):
        while True:
            time.sleep(0.02)
            self._pull(960)

    def feed(self, data: bytes) -> None:
        with self.lock:
            self.buf += data

    def stop(self) -> None:
        with self.lock:
            self.buf.clear()
        self.silenced_at = None
        self.stop_at = time.perf_counter()

    def pending_s(self) -> float:
        return len(self.buf) / (TTS_RATE * 2)


# ----------------------------------------------------------------------------- speech services

def wav_bytes(pcm: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    return buf.getvalue()


def transcribe(http: httpx.Client, pcm: np.ndarray, hinglish: bool) -> tuple:
    t = time.perf_counter()
    r = http.post("https://api.sarvam.ai/speech-to-text", headers={"api-subscription-key": os.getenv("SARVAM_API_KEY")},
                  data={"language_code": "unknown" if hinglish else "en-IN"},
                  files={"file": ("clip.wav", wav_bytes(pcm), "audio/wav")})
    if r.status_code >= 400:
        raise RuntimeError(f"Sarvam HTTP {r.status_code}: {r.text[:150]}")
    return r.json()["transcript"], (time.perf_counter() - t) * 1000


# ----------------------------------------------------------------------------- the loop

class Loop:
    def __init__(self, args):
        self.args = args
        self.player = Player(args.output_device, simulated=args.simulate)
        # keep the connections to Sarvam and Deepgram open between turns (the default drops them after 5 s idle,
        # and a fresh connection costs ~0.4 s on every reply)
        self.http = httpx.Client(timeout=30, limits=httpx.Limits(keepalive_expiry=300))
        for url, hdr in (("https://api.deepgram.com/v1/models", {"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}"}),
                         ("https://api.sarvam.ai/", {})):
            try:
                self.http.get(url, headers=hdr)
            except Exception:
                pass
        self.turn_no = 0
        self.ping_lock = threading.Lock()   # held while a keep-alive ping is in flight
        try:   # the first speech request of a session is slower (~0.5 s); make a throwaway one now, audio discarded
            with self.http.stream("POST", f"https://api.deepgram.com/v1/speak?model={VOICE}&encoding=linear16&sample_rate={TTS_RATE}"
                                          f"&container=none", headers={"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}"},
                                  json={"text": "Ready."}) as r:
                for _ in r.iter_bytes():
                    pass
        except Exception:
            pass
        threading.Thread(target=self._keepalive, daemon=True).start()
        self.jobs: "queue.Queue" = queue.Queue()
        self.epoch = 0
        self.busy = False            # a reply is being prepared or spoken
        self.speaking = False
        self.turns, self.barges, self.ignored = [], [], 0
        self.print_lock = threading.Lock()
        self.last_activity = time.perf_counter()
        threading.Thread(target=self._worker, daemon=True).start()

    def _keepalive(self) -> None:
        """Deepgram closes idle connections after a few seconds; one tiny request every 2 s keeps ours open."""
        while True:
            time.sleep(2.0)
            if not self.speaking and not self.busy:
                with self.ping_lock:
                    try:
                        self.http.head("https://api.deepgram.com/", headers={"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}"})
                    except Exception:
                        pass

    def warm(self) -> None:
        """Open a fresh connection to Deepgram in the background. It drops idle connections after ~3-6 s and
        after an abandoned stream, and reconnecting would otherwise add ~0.5 s to the reply."""
        def go():
            try:
                self.http.head("https://api.deepgram.com/", headers={"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}"})
            except Exception:
                pass
        threading.Thread(target=go, daemon=True).start()

    def say(self, msg: str) -> None:
        with self.print_lock:
            print(f"\r{' ' * 100}\r{msg}", flush=True)

    def interrupt(self, why: str, heard_ms: float) -> None:
        was_speaking = self.speaking or self.player.pending_s() > 0
        played = self.player.played_bytes / (TTS_RATE * 2)
        self.epoch += 1
        self.player.stop()
        if was_speaking:
            time.sleep(0.05)   # let the next 20 ms block go out so the silence time can be read
            stop_ms = ((self.player.silenced_at or time.perf_counter()) - self.player.stop_at) * 1000
            self.barges.append({"why": why, "reply_played_s": round(played, 2), "speech_needed_ms": round(heard_ms),
                                "software_stop_ms": round(stop_ms, 1),
                                "device_buffer_ms": round(self.player.device_latency_ms)})
            self.say(f"  >> interrupted ({why}): it needed {heard_ms:.0f} ms of your voice, playback silenced "
                     f"{stop_ms:.0f} ms later (+ about {self.player.device_latency_ms:.0f} ms in the sound card); "
                     f"{played:.1f} s of the reply had been played")

    # --- reply worker: transcribe, choose a reply, speak it
    def _worker(self) -> None:
        while True:
            job = self.jobs.get()
            try:
                self._handle(job)
            except Exception as e:
                self.say(f"  !! {type(e).__name__}: {str(e)[:200]}")
            finally:
                self.busy = False
                self.speaking = False
                self.last_activity = time.perf_counter()

    def _handle(self, job: dict) -> None:
        if job["epoch"] != self.epoch:
            return
        if job["kind"] == "say":
            self._speak(job["text"], job["epoch"], {})
            return
        text, stt_ms = transcribe(self.http, job["clip"], self.args.hinglish)
        if job["epoch"] != self.epoch:
            self.say(f"  (you spoke again; dropped \"{text}\")")
            return
        if not text.strip():
            self.say("  (nothing recognised)")
            return
        reply = reply_for(text)
        meta = {"speech_s": round(job["speech_s"], 2), "text": text, "reply": reply, "stt_ms": round(stt_ms),
                "silence_wait_ms": round(job["wait_ms"]), "hangover_s": job["hangover"], "turn": self._next_turn()}
        self._speak(reply, job["epoch"], meta)

    def _next_turn(self) -> int:
        self.turn_no += 1
        return self.turn_no

    def _speak(self, reply: str, epoch: int, meta: dict) -> None:
        with self.ping_lock:     # a ping in flight owns the open connection; wait for it (~0.1 s) instead of reconnecting
            pass
        t0 = time.perf_counter()
        first_ms, sent = None, 0
        self.speaking = True
        with self.http.stream("POST", f"https://api.deepgram.com/v1/speak?model={VOICE}&encoding=linear16&sample_rate={TTS_RATE}"
                                      f"&container=none", headers={"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}"},
                              json={"text": reply}) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"Deepgram HTTP {r.status_code}: {r.read()[:150]!r}")
            for chunk in r.iter_bytes():
                if epoch != self.epoch:        # interrupted while still generating: dropping the stream stops the download
                    if meta:
                        meta["interrupted"] = True
                    return
                self.player.feed(chunk)
                sent += len(chunk)
                if first_ms is None and sent >= 4800:
                    first_ms = (time.perf_counter() - t0) * 1000
                    if meta:
                        meta["tts_first_audio_ms"] = round(first_ms)
                        felt = meta["silence_wait_ms"] + meta["stt_ms"] + first_ms
                        meta["felt_ms"] = round(felt)
                        self.turns.append(meta)
                        self.say(f"[turn {meta['turn']}] you said ({meta['speech_s']} s): \"{meta['text']}\"\n"
                                 f"          waited {meta['silence_wait_ms'] / 1000:.2f} s silence + {meta['stt_ms'] / 1000:.2f} s transcript"
                                 f" + {first_ms / 1000:.2f} s voice  =  {felt / 1000:.2f} s until it started speaking\n"
                                 f"          reply: \"{reply if len(reply) < 90 else reply[:87] + '...'}\"")
        while self.player.pending_s() > 0 and epoch == self.epoch:
            time.sleep(0.02)
        if meta and epoch != self.epoch:
            meta["interrupted"] = True

    # --- microphone side
    def run(self, source) -> None:
        det = make_detector("silero")
        ep = Endpointer(det.frame_s, det.default_threshold, self.args.hangover)
        min_speech = self.args.min_speech
        audio = np.zeros(SR * 60 * 20, dtype=np.int16)
        n = cursor = 0
        run_s = 0.0
        barged = False
        in_utt = False
        status_t = 0.0
        try:
            import msvcrt
        except ImportError:
            msvcrt = None
        t_start = time.perf_counter()
        for chunk in source:
            if chunk is None:
                break
            audio[n:n + len(chunk)] = chunk
            n += len(chunk)
            while cursor + det.frame <= n:
                score = det.score(audio[cursor:cursor + det.frame])
                cursor += det.frame
                t_audio = cursor / SR
                speech = score >= det.default_threshold
                run_s = run_s + det.frame_s if speech else 0.0
                if speech:
                    self.last_activity = time.perf_counter()
                if speech and not barged and run_s >= min_speech and (self.busy or self.player.pending_s() > 0):
                    barged = True
                    self.interrupt("you spoke over it" if self.speaking else "you spoke again", run_s * 1000)
                ev = ep.push(t_audio, score)
                if ev is None:
                    continue
                if ev[0] == "start":
                    in_utt = True
                    self.warm()          # by the time you finish and it has been transcribed, the connection is fresh
                    continue
                _, start, speech_end, trigger = ev
                in_utt, barged = False, False
                dur = speech_end - start
                if dur < min_speech:
                    self.ignored += 1
                    self.say(f"  (ignored a {dur * 1000:.0f} ms sound)")
                    continue
                clip = audio[max(0, int((start - PRE_ROLL_S) * SR)):int(trigger * SR)].copy()
                if self.args.cue == "tick":
                    k = np.arange(int(0.06 * TTS_RATE))
                    tick = (np.sin(2 * np.pi * 1000 * k / TTS_RATE) * np.hanning(len(k)) * 5000).astype(np.int16)
                    self.player.feed(tick.tobytes())
                self.busy = True
                self.jobs.put({"kind": "turn", "clip": clip, "epoch": self.epoch, "speech_s": dur,
                               "wait_ms": (trigger - speech_end) * 1000, "hangover": ep.hangover_s})
            # keys and idle prompt
            while msvcrt and msvcrt.kbhit():
                ch = msvcrt.getwch().lower()
                if ch in "123":
                    ep.hangover_s = {"1": 0.3, "2": 0.5, "3": 0.8}[ch]
                    self.say(f"  [silence wait is now {ep.hangover_s:.1f} s]")
                elif ch in "456":
                    min_speech = {"4": 0.15, "5": 0.25, "6": 0.4}[ch]
                    self.say(f"  [speech needed to interrupt is now {min_speech:.2f} s]")
                elif ch == "q":
                    return
            if (self.args.idle and not self.busy and not in_utt
                    and time.perf_counter() - self.last_activity > self.args.idle):
                self.last_activity = time.perf_counter()
                self.busy = True
                self.jobs.put({"kind": "say", "text": "Are you still there?", "epoch": self.epoch})
            now = time.perf_counter()
            if now - status_t > 0.25 and not self.args.simulate:
                status_t = now
                state = "speaking" if self.speaking else "thinking" if self.busy else "listening"
                with self.print_lock:
                    print(f"\r  {state:<10} wait {ep.hangover_s:.1f}s  interrupt>={min_speech:.2f}s   ", end="", flush=True)
            if self.args.simulate and time.perf_counter() - t_start > self.args.simulate_seconds:
                return


def mic_source(args):
    import sounddevice as sd
    q: "queue.Queue[bytes]" = queue.Queue()
    stream = sd.RawInputStream(samplerate=SR, channels=1, dtype="int16", blocksize=512, device=args.input_device,
                               callback=lambda indata, f, t, s: q.put(bytes(indata)))
    stream.start()
    try:
        while True:
            try:
                yield np.frombuffer(q.get(timeout=0.1), dtype=np.int16)
            except queue.Empty:
                yield np.zeros(0, dtype=np.int16)    # keeps the key check alive
    finally:
        stream.stop()


def simulated_source(args):
    """Replays recordings as if they came from the microphone, at real-time speed: the first command at 1 s, a
    second one `--interrupt-at` seconds in (so it lands in the middle of the long reply)."""
    from scipy.io import wavfile
    seg = ROOT / "03_Speech_To_Text" / "data" / "segments"
    timeline = np.zeros(SR * (args.simulate_seconds + 2), dtype=np.int16)
    for name, at in ((args.sim_first, 1.0), (args.sim_second, args.interrupt_at)):
        _, x = wavfile.read(seg / f"{name}.wav")
        timeline[int(at * SR):int(at * SR) + len(x)] = x
    t0 = time.perf_counter()
    pos = 0
    while pos + 512 <= len(timeline):
        due = t0 + (pos + 512) / SR
        time.sleep(max(0.0, due - time.perf_counter()))
        yield timeline[pos:pos + 512]
        pos += 512
    yield None


def summary(loop: "Loop", args) -> None:
    def med(key):
        v = [t[key] for t in loop.turns if key in t]
        return round(statistics.median(v)) if v else None
    out = {"turns": len(loop.turns), "interruptions": loop.barges, "ignored_sounds": loop.ignored,
           "median_ms": {k: med(k) for k in ("silence_wait_ms", "stt_ms", "tts_first_audio_ms", "felt_ms")},
           "settings": {"hangover_s_start": args.hangover, "min_speech_s_start": args.min_speech}, "turn_log": loop.turns}
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    (HERE / "results").mkdir(exist_ok=True)
    path = HERE / "results" / f"turns_{stamp}{'_sim' if args.simulate else ''}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(loop.turns)} turns, {len(loop.barges)} interruptions, {loop.ignored} short sounds ignored")
    print(f"median: silence wait {out['median_ms']['silence_wait_ms']} ms, transcript {out['median_ms']['stt_ms']} ms, "
          f"voice start {out['median_ms']['tts_first_audio_ms']} ms, total until it spoke {out['median_ms']['felt_ms']} ms")
    for b in loop.barges:
        print(f"interruption: needed {b['speech_needed_ms']} ms of speech, silenced in {b['software_stop_ms']} ms "
              f"(+{b['device_buffer_ms']} ms sound card), after {b['reply_played_s']} s of reply")
    print(f"saved {path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--input-device", help="microphone number or name part (default: system default)")
    ap.add_argument("--output-device", help="headphones number or name part (default: system default)")
    ap.add_argument("--hangover", type=float, default=0.5, help="silence (s) before it decides you finished")
    ap.add_argument("--min-speech", type=float, default=0.25, help="speech (s) needed to interrupt; shorter sounds are ignored")
    ap.add_argument("--cue", choices=["none", "tick"], default="none")
    ap.add_argument("--idle", type=float, default=0, help="say 'Are you still there?' after this many quiet seconds (0 = off)")
    ap.add_argument("--hinglish", action="store_true")
    ap.add_argument("--simulate", action="store_true", help="replay recordings instead of the microphone; no sound out")
    ap.add_argument("--simulate-seconds", type=int, default=22)
    ap.add_argument("--sim-first", default="V6_4", help="segment played first (default: 'Tell me the title...' = long reply)")
    ap.add_argument("--sim-second", default="V1_1", help="segment played to interrupt (default: 'Scroll down')")
    ap.add_argument("--interrupt-at", type=float, default=9.0)
    args = ap.parse_args()

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return 0
    for key in ("input_device", "output_device"):
        v = getattr(args, key)
        if v is not None and v.isdigit():
            setattr(args, key, int(v))
    for need in ("SARVAM_API_KEY", "DEEPGRAM_API_KEY"):
        if not os.getenv(need):
            raise SystemExit(f"{need} is not set in .env")

    if not args.simulate:
        import sounddevice as sd
        di, do = sd.query_devices(args.input_device if args.input_device is not None else sd.default.device[0], "input"), \
                 sd.query_devices(args.output_device if args.output_device is not None else sd.default.device[1], "output")
        print(f"Microphone: {di['name']}\nOutput:     {do['name']}   <- should be your headphones\n")
        print("Say a command (\"scroll down\", \"search for lofi music\"). Say \"tell me about it\" for a LONG reply to interrupt.")
        print("Keys: 1 2 3 = silence wait 0.3/0.5/0.8 s   4 5 6 = speech to interrupt 0.15/0.25/0.4 s   q = quit\n", flush=True)
    loop = Loop(args)
    source = simulated_source(args) if args.simulate else mic_source(args)
    try:
        loop.run(source)
    except KeyboardInterrupt:
        pass
    time.sleep(0.2)
    summary(loop, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
