"""A small always-on-top floating widget showing what Jarvis is doing right now.

Tkinter (stdlib, no install needed) owns the main thread via Overlay.run() -> mainloop(); every other part
of the app (mic capture, the browser's asyncio loop, the job-processing worker) runs in a background thread
and reports state through OverlayState, which Overlay polls on a timer instead of being pushed to directly -
Tkinter widgets may only be touched from the thread that created them.
"""
import threading
import tkinter as tk
from tkinter import simpledialog

STATE_COLORS = {"listening": "#888888", "thinking": "#f1c40f", "speaking": "#3498db", "error": "#e74c3c"}
# "listening"'s label is built per-instance from assistant_name (below), not hardcoded here, so it can
# never drift out of sync with config.ASSISTANT_NAME.
STATE_LABELS = {"thinking": "thinking", "speaking": "speaking", "error": "error"}


class OverlayState:
    """Thread-safe: one or more background threads call set(), the Tkinter main thread calls get()."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = "listening"
        self._detail = ""

    def set(self, state: str, detail: str = "") -> None:
        with self._lock:
            self._state, self._detail = state, detail

    def get(self) -> tuple:
        with self._lock:
            return self._state, self._detail


class Overlay:
    def __init__(self, state: OverlayState, assistant_name: str = "Jarvis", on_pick_devices=None):
        self.state = state
        self.assistant_name = assistant_name
        self.on_pick_devices = on_pick_devices
        self._drag = {"x": 0, "y": 0}
        self._listening_label = f"listening (say “{assistant_name}” first)"

        self.root = tk.Tk()
        self.root.title(assistant_name)
        self.root.overrideredirect(True)      # borderless
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)  # slightly see-through
        self.root.configure(bg="#1e1e1e")
        self.root.geometry("+40+40")

        frame = tk.Frame(self.root, bg="#1e1e1e", padx=12, pady=8)
        frame.pack()
        self.dot = tk.Canvas(frame, width=14, height=14, bg="#1e1e1e", highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 8))
        self._dot_id = self.dot.create_oval(2, 2, 12, 12, fill=STATE_COLORS.get("listening", "#888888"), outline="")
        self.label = tk.Label(frame, text=f"{assistant_name}: waiting", fg="white", bg="#1e1e1e", font=("Segoe UI", 10))
        self.label.pack(side="left")
        gear = tk.Label(frame, text="⚙", fg="#aaaaaa", bg="#1e1e1e", font=("Segoe UI", 12), cursor="hand2")
        gear.pack(side="left", padx=(10, 0))
        gear.bind("<Button-1>", lambda e: self.on_pick_devices() if self.on_pick_devices else None)

        for w in (self.root, frame, self.label, self.dot):
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._drag_move)

        self._poll()

    def _start_drag(self, event) -> None:
        self._drag = {"x": event.x, "y": event.y}

    def _drag_move(self, event) -> None:
        x = self.root.winfo_x() + event.x - self._drag["x"]
        y = self.root.winfo_y() + event.y - self._drag["y"]
        self.root.geometry(f"+{x}+{y}")

    def _poll(self) -> None:
        state, detail = self.state.get()
        self.dot.itemconfig(self._dot_id, fill=STATE_COLORS.get(state, "#888888"))
        label = self._listening_label if state == "listening" else STATE_LABELS.get(state, state)
        text = f"{self.assistant_name}: {label}"
        if detail:
            text += f" – {detail[:40]}"
        self.label.config(text=text)
        self.root.after(150, self._poll)

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        try:
            self.root.after(0, self.root.destroy)
        except Exception:
            pass


def pick_devices(root: tk.Tk, current: dict) -> dict:
    """A minimal blocking dialog (must be called from the Tkinter thread) to choose input/output audio
    devices by index, backed by sounddevice.query_devices(). Returns the (possibly unchanged) device dict."""
    import sounddevice as sd

    devices = sd.query_devices()
    lines = []
    for i, d in enumerate(devices):
        kind = []
        if d["max_input_channels"] > 0:
            kind.append("in")
        if d["max_output_channels"] > 0:
            kind.append("out")
        if kind:
            lines.append(f"[{i}] ({'/'.join(kind)}) {d['name']}")
    listing = "\n".join(lines)

    from .config import ASSISTANT_NAME

    result = dict(current)
    inp = simpledialog.askstring(
        f"{ASSISTANT_NAME} - input device", f"Type an input device index (blank = system default):\n\n{listing}",
        initialvalue=str(current.get("input_device", "")), parent=root)
    if inp is not None:
        result["input_device"] = int(inp) if inp.strip().isdigit() else None
    outp = simpledialog.askstring(
        f"{ASSISTANT_NAME} - output device", f"Type an output device index (blank = system default):\n\n{listing}",
        initialvalue=str(current.get("output_device", "")), parent=root)
    if outp is not None:
        result["output_device"] = int(outp) if outp.strip().isdigit() else None
    return result
