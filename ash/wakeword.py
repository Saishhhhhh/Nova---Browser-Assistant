"""Gates commands on Rhasspy's own name, so background conversation in the room doesn't get acted on.

This is NOT an acoustic wake-word model (Porcupine/openWakeWord) - that needs a new ML dependency and,
for a custom name like "Rhasspy", a trained model via an external account. Instead it reuses the same "strip a
known prefix off the transcript" pattern already proven in router.py's FILLER/CORRECTION handling: the
existing VAD+STT pipeline keeps deciding when you've finished speaking (unchanged), and this just decides,
after transcription, whether what you said was actually addressed to Rhasspy. A real offline wake-word engine
would react faster and run with the mic always analysed locally; this reacts only after a full utterance is
already transcribed - a deliberate, documented trade-off, not an oversight (see WRITEUP.md).

Found live: anchoring the match to the very start of the sentence rejected perfectly natural phrasing -
"Can you scroll down, Rhasspy?" (name at the end) and "Uh, hi Rhasspy, can you open X" (name after a greeting) both
got ignored, even though they were clearly addressed to Rhasspy. The name can now appear anywhere in the
sentence; only the matched word (plus an immediate greeting before it) is removed, not the whole prefix.
"""
import re

from .config import ASSISTANT_NAME

_WAKE = re.compile(rf"\b(?:hey|hi|okay|ok)?\s*{re.escape(ASSISTANT_NAME)}\b[\s,.:]*", re.I)


def strip_wake_word(text: str) -> tuple:
    """Returns (addressed, remainder). addressed=False means: this wasn't said to Rhasspy - show it was heard,
    but don't act on it."""
    t = text.strip()
    m = _WAKE.search(t)
    if not m:
        return False, text
    remainder = (t[:m.start()] + " " + t[m.end():]).strip()
    remainder = re.sub(r"\s+", " ", remainder)
    remainder = re.sub(r"\s*,\s*([.?!]|$)", r"\1", remainder).strip(" ,")
    return True, remainder
