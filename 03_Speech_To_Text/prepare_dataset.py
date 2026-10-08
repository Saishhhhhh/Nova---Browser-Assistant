"""Turn the recordings into a test set. Offline: no API calls.

  python prepare_dataset.py

For every recording in recordings/ (V0 ... V10, any case, .m4a/.wav/...):
  1. converts it to 16 kHz mono 16-bit WAV (needs ffmpeg),
  2. cuts it into single commands on the pauses (energy based),
  3. pairs each command with its line from recording_script.md,
and writes data/manifest.json plus one WAV per command in data/segments/.
Each segment keeps ~0.3 s of silence before and ~1.0 s after the speech, so a streaming engine
has room to decide you have finished. The manifest records where the speech starts and ends.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
RECORDINGS = HERE / "recordings"
DATA = HERE / "data"
WAV_DIR = DATA / "wav"
SEG_DIR = DATA / "segments"
SCRIPT = HERE / "recording_script.md"

FRAME_MS = 20
MIN_SPEECH_S = 0.20           # shorter blips (clicks, breaths) are not commands
GAPS_TO_TRY = (0.9, 0.7, 1.1, 0.5, 1.4)  # pause lengths (s) that separate two commands
PAD_BEFORE_S, PAD_AFTER_S = 0.3, 1.0


def parse_script() -> dict:
    lines, current = {}, None
    for raw in SCRIPT.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#{2,3}\s+(V\d+)\b", raw)
        if m:
            current = m.group(1).upper()
            lines[current] = []
            continue
        m = re.match(r"^\d+\.\s+(.*\S)\s*$", raw)
        if m and current:
            lines[current].append(m.group(1))
    return lines


def to_wav(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "16000",
                    "-sample_fmt", "s16", str(dst)], check=True)


def speech_regions(x: np.ndarray, sr: int, gap_s: float) -> list:
    """(start_s, end_s) of speech, merging pauses shorter than gap_s."""
    n = int(sr * FRAME_MS / 1000)
    frames = x[: len(x) // n * n].reshape(-1, n).astype(np.float32)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) / 32768 + 1e-9)
    threshold = max(np.percentile(db, 10) + 15, -50)
    voiced = db > threshold
    regions, start, last = [], None, None
    max_gap = int(gap_s * 1000 / FRAME_MS)
    for i, v in enumerate(voiced):
        if v:
            if start is None:
                start = i
            elif i - last > max_gap:
                regions.append((start, last))
                start = i
            last = i
    if start is not None:
        regions.append((start, last))
    out = [(a * FRAME_MS / 1000, (b + 1) * FRAME_MS / 1000) for a, b in regions]
    return [(a, b) for a, b in out if b - a >= MIN_SPEECH_S]


def main() -> int:
    if not RECORDINGS.exists() or not any(RECORDINGS.iterdir()):
        print(f"No recordings found in {RECORDINGS}")
        return 1
    script = parse_script()
    SEG_DIR.mkdir(parents=True, exist_ok=True)
    manifest, problems = [], []

    files = {}
    for p in RECORDINGS.iterdir():
        m = re.match(r"^(v\d+)\.", p.name, re.I)
        if m:
            files[m.group(1).upper()] = p

    print(f"{'file':<6}{'length':>8}  {'commands':>9}  gap  details")
    for vid in sorted(files, key=lambda s: int(s[1:])):
        wav = WAV_DIR / f"{vid}.wav"
        to_wav(files[vid], wav)
        sr, x = wavfile.read(wav)
        expected = script.get(vid, [])
        chosen, regions = None, []
        for gap in GAPS_TO_TRY:
            regions = speech_regions(x, sr, gap)
            if len(regions) == len(expected):
                chosen = gap
                break
        if chosen is None:
            regions = speech_regions(x, sr, GAPS_TO_TRY[0])
            problems.append(f"{vid}: found {len(regions)} commands, script has {len(expected)}")
        status = f"{len(regions)}/{len(expected)}" + ("" if chosen else "  <-- MISMATCH")
        spans = ", ".join(f"{b - a:.1f}s" for a, b in regions)
        print(f"{vid:<6}{len(x) / sr:>7.1f}s  {status:>9}  {chosen or '-':>3}  {spans}")
        if chosen is None:
            continue
        for k, (a, b) in enumerate(regions, 1):
            lo = max(0.0, a - PAD_BEFORE_S)
            hi = min(len(x) / sr, b + PAD_AFTER_S)
            if k < len(regions):  # never run into the next command
                hi = min(hi, (b + regions[k][0]) / 2 + 0.3)
            seg = SEG_DIR / f"{vid}_{k}.wav"
            wavfile.write(seg, sr, x[int(lo * sr): int(hi * sr)])
            manifest.append({
                "id": f"{vid}_{k}", "file": str(seg.relative_to(HERE)), "text": expected[k - 1],
                "speech_start_s": round(a - lo, 3), "speech_end_s": round(b - lo, 3),
                "duration_s": round(hi - lo, 3), "source": vid,
            })

    if "V0" in files:
        sr, x = wavfile.read(WAV_DIR / "V0.wav")
        print(f"\nV0 (silence): {len(x) / sr:.1f}s, copied as data/wav/V0.wav "
              f"({len(speech_regions(x, sr, 0.9))} speech-like regions found; should be 0)")
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nwrote {len(manifest)} commands to {DATA / 'manifest.json'}")
    if problems:
        print("PROBLEMS:\n  " + "\n  ".join(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
