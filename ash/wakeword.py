"""Gates commands on Ash's own name, so background conversation in the room doesn't get acted on.

This is NOT an acoustic wake-word model (Porcupine/openWakeWord) - that needs a new ML dependency and,
for a custom name like "Ash", a trained model via an external account. Instead it reuses the same "strip a
known prefix off the transcript" pattern already proven in router.py's FILLER/CORRECTION handling: the
existing VAD+STT pipeline keeps deciding when you've finished speaking (unchanged), and this just decides,
after transcription, whether what you said was actually addressed to Ash. A real offline wake-word engine
would react faster and run with the mic always analysed locally; this reacts only after a full utterance is
already transcribed - a deliberate, documented trade-off, not an oversight (see WRITEUP.md).
"""
import re

from .config import ASSISTANT_NAME

_WAKE = re.compile(rf"^(?:hey|hi|okay|ok)?\s*{re.escape(ASSISTANT_NAME)}\b[\s,.:]*", re.I)


def strip_wake_word(text: str) -> tuple:
    """Returns (addressed, remainder). addressed=False means: this wasn't said to Ash - show it was heard,
    but don't act on it."""
    m = _WAKE.match(text.strip())
    if not m:
        return False, text
    return True, text[m.end():].strip()
