"""Gates commands on Nova's own name, so background conversation in the room doesn't get acted on.

This is NOT the acoustic wake-word model (openWakeWord, in openwakeword_wake.py) - this is the
text-based fallback/companion signal: it reuses the same "strip a known prefix off the transcript"
pattern already proven in router.py's FILLER/CORRECTION handling. The existing VAD+STT pipeline keeps
deciding when you've finished speaking (unchanged), and this just decides, after transcription, whether
what you said was actually addressed to Nova. It reacts only after a full utterance is already
transcribed - a deliberate, documented trade-off, not an oversight (see WRITEUP.md).

Found live: anchoring the match to the very start of the sentence rejected perfectly natural phrasing -
"Can you scroll down, Nova?" (name at the end) and "Uh, hi Nova, can you open X" (name after a greeting) both
got ignored, even though they were clearly addressed to Nova. The name can now appear anywhere in the
sentence; only the matched word (plus an immediate greeting before it) is removed, not the whole prefix.
"""
import re

from .config import ASSISTANT_NAME

_WAKE = re.compile(rf"\b(?:hey|hi|okay|ok)?\s*{re.escape(ASSISTANT_NAME)}\b[\s,.:]*", re.I)


def strip_wake_word(text: str) -> tuple:
    """Returns (addressed, remainder). addressed=False means: this wasn't said to Nova - show it was heard,
    but don't act on it."""
    t = text.strip()
    m = _WAKE.search(t)
    if not m:
        return False, text
    remainder = (t[:m.start()] + " " + t[m.end():]).strip()
    remainder = re.sub(r"\s+", " ", remainder)
    remainder = re.sub(r"\s*,\s*([.?!]|$)", r"\1", remainder).strip(" ,")
    return True, remainder
