"""Plot a recording with the truth boundaries and what Silero / Energy detected, to check the labels by eye.

  python check_labels.py V5 [out.png]
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vad_bench import load_recordings  # noqa: E402
from vad_core import SR, frame_scores, make_detector, segment  # noqa: E402

vid = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else f"labels_{vid}.png"
data = load_recordings()
x, truth = data["audio"][vid], data["truth"][vid]
t = np.arange(len(x)) / SR
fig, axes = plt.subplots(3, 1, figsize=(15, 8), sharex=True)
axes[0].plot(t, x, lw=0.4, color="0.3")
axes[0].set_title(f"{vid}: waveform (green = truth from Experiment 3, orange = Silero 0.5 / 300 ms)")
sil = make_detector("silero")
sc = frame_scores(sil, x)
utts = segment(sc, sil.frame_s, 0.5, 0.3)
for k, (a, b) in enumerate(truth):
    for ax in axes:
        ax.axvspan(a, b, color="green", alpha=0.18)
    axes[0].text(a, axes[0].get_ylim()[1] * 0.85, str(k), color="green")
for u in utts:
    for ax in axes:
        ax.axvspan(u["start"], u["speech_end"], ymin=0, ymax=0.12, color="orange")
axes[1].plot((np.arange(len(sc)) + 1) * sil.frame_s, sc, color="tab:orange")
axes[1].axhline(0.5, color="r", lw=0.5)
axes[1].set_title("Silero speech probability")
n = 320
db = 20 * np.log10(np.sqrt((x[: len(x) // n * n].reshape(-1, n).astype(float) ** 2).mean(axis=1)) / 32768 + 1e-9)
axes[2].plot((np.arange(len(db)) + 1) * n / SR, db, lw=0.7)
axes[2].set_title("Loudness (dB per 20 ms)")
plt.tight_layout()
plt.savefig(out, dpi=80)
print("saved", out)
