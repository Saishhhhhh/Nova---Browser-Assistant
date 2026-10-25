"""The voice turn-taking loop: microphone -> Silero VAD -> STT -> (router, wired in by ash/app.py) -> TTS,
with barge-in (speak over a reply and playback stops instantly). Originated as Experiment 6/7; this is the
production version - the standalone demo CLI, canned replies, and recorded-audio simulation mode from the
experiment version are gone (see experiments/06_Turn_Taking/voice_loop.py for those). Use HEADPHONES.
"""
import io
import os
import queue
import threading
import time
import wave

import httpx
import numpy as np

from . import openwakeword_wake
from .vad import SR, Endpointer, make_detector

VOICE = "aura-2-phoebe-en"
TTS_RATE = 24000
PRE_ROLL_S = 0.3
WAKE_GRACE_S = 8.0   # how long after the wake word fires an utterance still counts as addressed - covers
                     # both "Jarvis, open github" (one breath) and "Jarvis." <pause> "open github." (two)


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


# Words this app's own commands/names need right, that generic speech models have no reason to know. Sent to
# ElevenLabs as `keyterms`. Found live: "Saish" (the user's own name, spelled out letter by letter as a search
# query) was consistently misheard as "size" on Sarvam; Experiment 3 found keyterms gave no measurable accuracy
# gain on its own hard-name list, but that list never included this word, so this is re-measured on real use.
PERSONAL_VOCAB = ["Saish", "saishhhhhh", "GitHub", "github.com", "Wikipedia", "Flipkart", "books.toscrape.com"]


def transcribe(http: httpx.Client, pcm: np.ndarray, hinglish: bool, engine: str = "elevenlabs") -> tuple:
    """engine: "elevenlabs" (default, most accurate, ~0.8 s) or "sarvam" (fastest, ~0.14 s, better for Hinglish)."""
    t = time.perf_counter()
    if engine == "sarvam":
        r = http.post("https://api.sarvam.ai/speech-to-text", headers={"api-subscription-key": os.getenv("SARVAM_API_KEY")},
                      data={"language_code": "unknown" if hinglish else "en-IN"},
                      files={"file": ("clip.wav", wav_bytes(pcm), "audio/wav")})
        if r.status_code >= 400:
            raise RuntimeError(f"Sarvam HTTP {r.status_code}: {r.text[:150]}")
        return r.json()["transcript"], (time.perf_counter() - t) * 1000
    data = {"model_id": "scribe_v2", "tag_audio_events": "false", "diarize": "false", "language_code": "en",
             "keyterms": PERSONAL_VOCAB}
    r = http.post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": os.getenv("ELEVENLABS_API_KEY")},
                  data=data, files={"file": ("clip.wav", wav_bytes(pcm), "audio/wav")})
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}: {r.text[:150]}")
    return r.json()["text"], (time.perf_counter() - t) * 1000


def save_clip(pcm: np.ndarray, turn_no: int, out_dir) -> None:
    """Saves the raw audio of a turn, so any failing transcript can be replayed exactly against any engine
    instead of re-testing live. Called for every turn, not just failures, since "failing" is only known later."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"turn_{turn_no:03d}.wav").write_bytes(wav_bytes(pcm))


# ----------------------------------------------------------------------------- the loop

class Loop:
    def __init__(self, args, on_state=None):
        self.args = args
        self.on_state = on_state   # optional callback(state: str) -> None, for the overlay widget
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
        self.reply_base = 0               # player.played_bytes when the current reply began
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
        self.wake_until = 0.0   # a VAD utterance whose end-time is <= this (same clock as run()'s t_audio)
                                 # was triggered acoustically by the real wake-word detector, not just
                                 # because it contains the wake word in its transcript. 0.0 (the default)
                                 # means "never" until the detector (if available) actually fires once.
        self._wake = None
        if openwakeword_wake.available():
            try:
                self._wake = openwakeword_wake.WakeDetector()
            except Exception as e:
                print(f"openWakeWord failed to start, falling back to text-based wake-word detection: {e}", flush=True)
        threading.Thread(target=self._worker, daemon=True).start()

    def _keepalive(self) -> None:
        """Deepgram closes idle connections after a few seconds; one tiny request every 2 s keeps ours open."""
        while True:
            time.sleep(2.0)
            if not self.speaking:     # also while a command is being worked on: a long agent run outlasts the idle limit
                with self.ping_lock:
                    try:
                        self.http.head("https://api.deepgram.com/", headers={"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}"})
                    except Exception:
                        pass

    def submit(self, job: dict) -> None:
        self.jobs.put(job)

    def barge_applies(self) -> bool:
        """Does speech right now count as an interruption? Here: yes while a reply is prepared or spoken."""
        return self.busy or self.player.pending_s() > 0

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
        played = (self.player.played_bytes - self.reply_base) / (TTS_RATE * 2)   # this reply only, not the session
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
        """Always overridden by AppLoop, which wires in the router, memory, and planner. Kept only so a
        subclass that forgets to override it fails loudly instead of silently doing nothing."""
        raise NotImplementedError("Loop._handle must be overridden (see AppLoop in ash/app.py)")

    def _next_turn(self) -> int:
        self.turn_no += 1
        return self.turn_no

    def _speak(self, reply: str, epoch: int, meta: dict, on_first_audio=None) -> None:
        """Speak `reply`. If the pooled connection turned out to be dead (the server closed it), try once more."""
        for attempt in (1, 2):
            self._fed = False
            try:
                return self._speak_once(reply, epoch, meta, on_first_audio)
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError, httpx.WriteError):
                if attempt == 2 or self._fed:
                    raise
                time.sleep(0.05)

    def _speak_once(self, reply: str, epoch: int, meta: dict, on_first_audio=None) -> None:
        with self.ping_lock:     # a ping in flight owns the open connection; wait for it (~0.1 s) instead of reconnecting
            pass
        t0 = time.perf_counter()
        first_ms, sent = None, 0
        self.speaking = True
        self.reply_base = self.player.played_bytes + int(self.player.pending_s() * TTS_RATE * 2)
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
                self._fed = True
                sent += len(chunk)
                if first_ms is None and sent >= 4800:
                    now = time.perf_counter()
                    first_ms = (now - t0) * 1000
                    if on_first_audio:
                        on_first_audio(now, first_ms)
                    if meta:
                        meta["tts_first_audio_ms"] = round(first_ms)
                        route_ms = meta.get("route_ms", 0)
                        felt = (now - meta["t_speech_end"]) * 1000 if "t_speech_end" in meta \
                            else meta["silence_wait_ms"] + meta["stt_ms"] + route_ms + first_ms
                        meta["felt_ms"] = round(felt)
                        self.turns.append(meta)
                        route = f" + {route_ms / 1000:.2f} s browser step [{meta.get('tier', '')}]" if route_ms else ""
                        self.say(f"[turn {meta['turn']}] you said ({meta['speech_s']} s): \"{meta['text']}\"\n"
                                 f"          waited {meta['silence_wait_ms'] / 1000:.2f} s silence + {meta['stt_ms'] / 1000:.2f} s transcript"
                                 f"{route} + {first_ms / 1000:.2f} s voice  =  {felt / 1000:.2f} s until it started speaking\n"
                                 f"          reply: \"{reply if len(reply) < 90 else reply[:87] + '...'}\"")
        while self.player.pending_s() > 0 and epoch == self.epoch:
            time.sleep(0.02)
        self.speaking = False
        if meta and epoch != self.epoch:
            meta["interrupted"] = True

    # --- microphone side
    def run(self, source) -> None:
        det = make_detector("silero")
        ep = Endpointer(det.frame_s, det.default_threshold, self.args.hangover)
        min_speech = self.args.min_speech
        wake = self._wake
        audio = np.zeros(SR * 60 * 20, dtype=np.int16)
        n = cursor = wcursor = 0
        run_s = 0.0
        barged = False
        in_utt = False
        status_t = 0.0
        try:
            import msvcrt
        except ImportError:
            msvcrt = None
        for chunk in source:
            if chunk is None:
                break
            audio[n:n + len(chunk)] = chunk
            n += len(chunk)
            if wake is not None:
                # Independent cursor: the wake detector's frame size (1280 samples/80ms) doesn't line up
                # with Silero's (512 samples/32ms), so it scans the same growing buffer on its own schedule.
                while wcursor + wake.frame_length <= n:
                    wframe = audio[wcursor:wcursor + wake.frame_length]
                    wcursor += wake.frame_length
                    wscore = wake.score(wframe)
                    if os.getenv("WAKE_DEBUG") and wscore > 0.1:
                        self.say(f"  (wake score {wscore:.2f} at {wcursor / SR:.2f}s)")
                    if wscore >= wake.threshold:
                        self.wake_until = (wcursor / SR) + WAKE_GRACE_S
                        self.say("  (wake word heard - listening for a command)")
            while cursor + det.frame <= n:
                score = det.score(audio[cursor:cursor + det.frame])
                cursor += det.frame
                t_audio = cursor / SR
                speech = score >= det.default_threshold
                run_s = run_s + det.frame_s if speech else 0.0
                if speech:
                    self.last_activity = time.perf_counter()
                if speech and not barged and run_s >= min_speech and self.barge_applies():
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
                if wake is not None and trigger > self.wake_until:
                    # Found live: a short "Jarvis, open github" utterance sometimes got rejected even
                    # though the word WAS in the audio, because the wake detector needs a little trailing
                    # context to recognise a word confidently, and VAD can decide the utterance is over
                    # before that recognition catches up. Give it a brief window (0.6 s) to finish
                    # processing audio it already has, pulling a bit more live audio only if it runs out -
                    # not a fixed delay on every command, just on the rare case that's actually ambiguous.
                    catchup_deadline = time.perf_counter() + 0.6
                    while trigger > self.wake_until and time.perf_counter() < catchup_deadline:
                        caught_up = False
                        while wcursor + wake.frame_length <= n:
                            wframe = audio[wcursor:wcursor + wake.frame_length]
                            wcursor += wake.frame_length
                            wscore = wake.score(wframe)
                            if os.getenv("WAKE_DEBUG") and wscore > 0.1:
                                self.say(f"  (wake score {wscore:.2f} at {wcursor / SR:.2f}s, catching up)")
                            if wscore >= wake.threshold:
                                self.wake_until = (wcursor / SR) + WAKE_GRACE_S
                                self.say("  (wake word heard - listening for a command)")
                                break
                            caught_up = True
                        if not caught_up:
                            extra = next(source, None)
                            if extra is not None and len(extra):
                                audio[n:n + len(extra)] = extra
                                n += len(extra)
                            else:
                                time.sleep(0.02)
                clip = audio[max(0, int((start - PRE_ROLL_S) * SR)):int(trigger * SR)].copy()
                if self.args.cue == "tick":
                    k = np.arange(int(0.06 * TTS_RATE))
                    tick = (np.sin(2 * np.pi * 1000 * k / TTS_RATE) * np.hanning(len(k)) * 5000).astype(np.int16)
                    self.player.feed(tick.tobytes())
                self.busy = True
                self.submit({"kind": "turn", "clip": clip, "epoch": self.epoch, "speech_s": dur,
                               "wait_ms": (trigger - speech_end) * 1000, "hangover": ep.hangover_s,
                               "t_trigger": time.perf_counter(),
                               "wake_addressed": wake is not None and trigger <= self.wake_until})
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
                if self.on_state:
                    self.on_state(state)
                with self.print_lock:
                    print(f"\r  {state:<10} wait {ep.hangover_s:.1f}s  interrupt>={min_speech:.2f}s   ", end="", flush=True)


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


