"""Nova's persona: just enough to greet you by name and recognise her own name - not a personality engine."""
from .config import ASSISTANT_NAME, USER_NAME

GREETING = f"Hi {USER_NAME}, I'm {ASSISTANT_NAME}. Say my name before a command and I'll get on it."
BRAVE_ALREADY_OPEN = (
    "Brave looks like it's already open. Close every Brave window and try again - "
    f"{ASSISTANT_NAME} needs sole use of your profile while she's running."
)
