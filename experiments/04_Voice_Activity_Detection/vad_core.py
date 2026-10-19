"""Shared VAD pieces for Experiment 4.

Three frame-level detectors (Silero, WebRTC, a plain energy baseline) that each turn one frame of
16 kHz audio into a score, and one streaming end-of-speech state machine (`Endpointer`) that turns
a stream of scores into "speech started" / "speech ended" events. The benchmark and the live
microphone tool both use exactly this code, so what the benchmark measures is what you hear live.
"""
import math
from collections import deque

import numpy as np

SR = 16000


class Detector:
    """One frame in (int16 samples), one score out. A frame counts as speech when score >= threshold."""
    name = ""
    frame = 0                 # samples per frame
    default_threshold = 0.5

    @property
    def frame_s(self) -> float:
        return self.frame / SR

    def reset(self) -> None:
        pass

    def score(self, frame: np.ndarray) -> float:
        raise NotImplementedError


class SileroDetector(Detector):
    """Small neural model; score is the speech probability (0..1). 32 ms frames."""
    name = "silero"
    frame = 512
    default_threshold = 0.5
    _model = None

    def __init__(self):
        import torch
        from silero_vad import load_silero_vad
        torch.set_num_threads(1)
        if SileroDetector._model is None:
            SileroDetector._model = load_silero_vad()
        self._torch = torch
        self.model = SileroDetector._model
        self.reset()

    def reset(self) -> None:
        self.model.reset_states()

    def score(self, frame: np.ndarray) -> float:
        x = self._torch.from_numpy(frame.astype(np.float32) / 32768.0)
        return float(self.model(x, SR).item())


class WebRtcDetector(Detector):
    """Rule-based detector from the WebRTC project; score is 0 or 1. 20 ms frames.
    aggressiveness 0 (lets most things through) to 3 (strictest)."""
    frame = 320
    default_threshold = 0.5

    def __init__(self, aggressiveness: int = 2):
        import webrtcvad
        self.vad = webrtcvad.Vad(aggressiveness)
        self.name = f"webrtc{aggressiveness}"

    def score(self, frame: np.ndarray) -> float:
        return 1.0 if self.vad.is_speech(frame.tobytes(), SR) else 0.0


class EnergyDetector(Detector):
    """Baseline: how many dB the frame is above the quietest recent sound (a running noise floor
    over the last 5 s). 20 ms frames. Score is that excess in dB."""
    name = "energy"
    frame = 320
    default_threshold = 12.0

    def __init__(self, window_s: float = 5.0):
        self.hist = deque(maxlen=int(window_s * SR / self.frame))

    def reset(self) -> None:
        self.hist.clear()

    def score(self, frame: np.ndarray) -> float:
        rms = math.sqrt(float(np.mean(frame.astype(np.float64) ** 2)))
        db = 20 * math.log10(rms / 32768 + 1e-9)
        self.hist.append(db)
        floor = max(float(np.percentile(self.hist, 10)), -60.0)
        return db - floor if db > -50 else 0.0


def make_detector(name: str) -> Detector:
    if name == "silero":
        return SileroDetector()
    if name.startswith("webrtc"):
        return WebRtcDetector(int(name[6:] or 2))
    if name == "energy":
        return EnergyDetector()
    raise ValueError(f"unknown detector {name}")


class Endpointer:
    """Streaming state machine. Feed it one (time, score) per frame; it says when speech started and
    when you have finished.

      start  : `min_speech_s` of consecutive speech frames. The start time is the first of those frames.
      end    : `hangover_s` of silence after the last speech frame. This wait is the delay the user feels.

    push() returns None, ("start", start_t, now) or ("end", start_t, speech_end_t, trigger_t), where
    trigger_t is the moment the end is declared (= speech_end_t + hangover_s).
    """

    def __init__(self, frame_s: float, threshold: float, hangover_s: float, min_speech_s: float = 0.1):
        self.frame_s, self.threshold, self.hangover_s = frame_s, threshold, hangover_s
        self.need = max(1, round(min_speech_s / frame_s))
        self.run = 0
        self.run_start = 0.0
        self.active = False
        self.start_t = 0.0
        self.last_speech_end = 0.0

    def push(self, t_end: float, score: float):
        speech = score >= self.threshold
        if not self.active:
            if speech:
                if self.run == 0:
                    self.run_start = t_end - self.frame_s
                self.run += 1
                if self.run >= self.need:
                    self.active = True
                    self.start_t = self.run_start
                    self.last_speech_end = t_end
                    return ("start", self.start_t, t_end)
            else:
                self.run = 0
            return None
        if speech:
            self.last_speech_end = t_end
            return None
        if t_end - self.last_speech_end >= self.hangover_s - 1e-9:
            self.active = False
            self.run = 0
            return ("end", self.start_t, self.last_speech_end, t_end)
        return None

    def flush(self, t_end: float):
        """End of the audio: close an utterance that is still open (trigger = end of audio)."""
        if self.active:
            self.active = False
            return ("end", self.start_t, self.last_speech_end, t_end)
        return None


def frame_scores(det: Detector, pcm: np.ndarray) -> np.ndarray:
    """Score every whole frame of a recording."""
    det.reset()
    n = len(pcm) // det.frame
    return np.array([det.score(pcm[i * det.frame:(i + 1) * det.frame]) for i in range(n)])


def segment(scores: np.ndarray, frame_s: float, threshold: float, hangover_s: float,
            min_speech_s: float = 0.1) -> list:
    """Run the Endpointer over saved scores. Returns [{start, speech_end, trigger}, ...] in seconds."""
    ep = Endpointer(frame_s, threshold, hangover_s, min_speech_s)
    out = []
    for i, s in enumerate(scores):
        ev = ep.push((i + 1) * frame_s, float(s))
        if ev and ev[0] == "end":
            out.append({"start": ev[1], "speech_end": ev[2], "trigger": ev[3]})
    ev = ep.flush(len(scores) * frame_s)
    if ev:
        out.append({"start": ev[1], "speech_end": ev[2], "trigger": ev[3]})
    return out
