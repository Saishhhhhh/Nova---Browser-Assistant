"""Real acoustic wake-word detection via openWakeWord: catches the wake word from raw audio the instant
it's spoken, instead of checking the transcript for it afterward (nova/wakeword.py's text-based check, which
stays as the fallback and as the thing that still cleans the word out of the final command text).

Free, fully local, no account needed - unlike Porcupine (Picovoice), which requires signing up and rejects
personal email addresses. openWakeWord ships pretrained models for a small fixed set of names ("alexa",
"hey_jarvis", "hey_mycroft", "hey_rhasspy") - the assistant was named Jarvis, then Mycroft, to use those
with zero training. "Nova" isn't one of the four, so this is a genuinely custom-trained model: synthetic
"Nova" clips generated with Piper TTS, mixed with real room impulse responses and background noise,
trained with openWakeWord's own training pipeline, exported to ONNX. Training-run numbers (see WRITEUP.md):
93.6% accuracy, 88.2% recall, ~13.5 false positives/hour at the training script's own internal threshold -
noticeably higher false-positive rate than the pretrained models this replaces, which is expected (a
custom model trained on ~2000 synthetic samples and synthetic background noise can't match a model tuned
on a much larger, more varied real-world dataset). THRESHOLD below is set more conservatively than the
pretrained models' 0.4 specifically because of that - it still needs real live tuning with WAKE_DEBUG=1.

If the `openwakeword` package isn't installed, available() is False and nothing else changes - app.py falls
back to the text-based check entirely.
"""
import os
from pathlib import Path

try:
    from openwakeword.model import Model
except ImportError:
    Model = None

# A local file path, not a pretrained name - openWakeWord's Model() accepts either; a path is used
# as-is (no download), and the dict key predict() returns scores under is the file's own basename
# without extension ("nova"), not the full path.
MODEL_PATH = os.getenv("OPENWAKEWORD_MODEL_PATH") or str(
    Path(__file__).resolve().parent / "wakeword_models" / "nova.onnx")
MODEL_KEY = Path(MODEL_PATH).stem
THRESHOLD = float(os.getenv("OPENWAKEWORD_THRESHOLD", "0.6"))   # more conservative than the pretrained
                                                                  # models' 0.4 - this custom model's own
                                                                  # measured false-positive rate is higher
                                                                  # (see module docstring); re-tune against
                                                                  # real WAKE_DEBUG=1 score logs.
FRAME_SAMPLES = 1280   # openWakeWord's fixed feed size: 80 ms at 16 kHz (unrelated to Silero's 512-sample
                       # frame also used for VAD - the mic loop runs both on independent cursors)
SAMPLE_RATE = 16000


def available() -> bool:
    return Model is not None and Path(MODEL_PATH).exists()


class WakeDetector:
    frame_length = FRAME_SAMPLES
    sample_rate = SAMPLE_RATE
    threshold = THRESHOLD

    def __init__(self):
        self._model = Model(wakeword_models=[MODEL_PATH], inference_framework="onnx")

    def score(self, frame) -> float:
        return self._model.predict(frame).get(MODEL_KEY, 0.0)

    def process(self, frame) -> bool:
        return self.score(frame) >= THRESHOLD

    def close(self) -> None:
        pass
