"""Real acoustic wake-word detection via openWakeWord: catches the wake word from raw audio the instant
it's spoken, instead of checking the transcript for it afterward (mycroft/wakeword.py's text-based check, which
stays as the fallback and as the thing that still cleans the word out of the final command text).

Free, fully local, no account needed - unlike Porcupine (Picovoice), which requires signing up and rejects
personal email addresses. The trade-off: openWakeWord ships pretrained models for a small fixed set of
names ("alexa", "hey_jarvis", "hey_mycroft", "hey_rhasspy") rather than letting you type any custom word -
which is why this assistant is named Mycroft: it's one of the pretrained models, so no custom training step
is needed. (The assistant was briefly named "Rhasspy" and then "Jarvis" for the same reason - both also
pretrained models - before settling on Mycroft.)

If the `openwakeword` package isn't installed, available() is False and nothing else changes - app.py falls
back to the text-based check entirely. The model file itself is downloaded once automatically (a few MB, no
account, no key) the first time this actually runs.
"""
import os

try:
    from openwakeword.model import Model
    from openwakeword.utils import download_models
except ImportError:
    Model = None
    download_models = None

MODEL_NAME = os.getenv("OPENWAKEWORD_MODEL", "hey_mycroft")
THRESHOLD = float(os.getenv("OPENWAKEWORD_THRESHOLD", "0.4"))   # found live: 0.5 missed an occasional
                                                                  # quieter/rushed "Hey Mycroft" that STT
                                                                  # still transcribed correctly (see the
                                                                  # text-match fallback in mycroft/app.py)
FRAME_SAMPLES = 1280   # openWakeWord's fixed feed size: 80 ms at 16 kHz (unrelated to Silero's 512-sample
                       # frame also used for VAD - the mic loop runs both on independent cursors)
SAMPLE_RATE = 16000


def available() -> bool:
    return Model is not None


class WakeDetector:
    frame_length = FRAME_SAMPLES
    sample_rate = SAMPLE_RATE
    threshold = THRESHOLD

    def __init__(self):
        download_models([MODEL_NAME])   # idempotent: skips re-downloading if already present
        self._model = Model(wakeword_models=[MODEL_NAME], inference_framework="onnx")

    def score(self, frame) -> float:
        return self._model.predict(frame).get(MODEL_NAME, 0.0)

    def process(self, frame) -> bool:
        return self.score(frame) >= THRESHOLD

    def close(self) -> None:
        pass
