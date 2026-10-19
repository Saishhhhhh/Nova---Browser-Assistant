"""Blind listening test: score how natural each voice sounds, without knowing which engine it is.

  python listen_test.py             # play and score (resumes where you stopped)
  python listen_test.py --reveal    # show the averages so far
  python listen_test.py --reset     # throw away the scores and start again

For each sentence you hear the same text from every engine, in random order, labelled A, B, C ...
Type a score from 1 (robotic / hard to listen to) to 10 (a real person), or  r  to hear it again.
All clips are played at the same loudness so a louder voice does not win. Use the headphones or
speakers you will really use. Ctrl+C is safe: scores are saved after every clip.
Only after the last clip are the engines revealed.
"""
import argparse
import json
import random
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
AUDIO = HERE / "data" / "audio"
SCORES = HERE / "results" / "listening_scores.json"
sys.path.insert(0, str(HERE))
from tts_bench import ENGINES, SENTENCES  # noqa: E402

TARGET_RMS = 0.06


def load(path: Path):
    with wave.open(str(path)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        return x, w.getframerate()


def play(path: Path) -> None:
    import sounddevice as sd
    x, sr = load(path)
    rms = float(np.sqrt(np.mean(x ** 2))) + 1e-9
    gain = min(TARGET_RMS / rms, 0.95 / (float(np.max(np.abs(x))) + 1e-9))
    sd.play(x * gain, sr)
    sd.wait()


def build_plan() -> list:
    """[(sentence id, [(letter, engine), ...]), ...] in a random but fixed order (saved with the scores)."""
    rng = random.Random()
    plan = []
    for sid in SENTENCES:
        engines = sorted(p.name.split("__")[0] for p in AUDIO.glob(f"*__{sid}.wav"))
        if len(engines) < 2:
            continue
        rng.shuffle(engines)
        plan.append((sid, [(chr(65 + i), e) for i, e in enumerate(engines)]))
    return plan


def reveal(data: dict) -> None:
    per_engine, per_group = {}, {}
    for sid, clips in data["plan"]:
        for letter, eng in clips:
            s = data["scores"].get(f"{sid}{letter}")
            if s is None:
                continue
            per_engine.setdefault(eng, []).append(s)
            per_group.setdefault((eng, "Hinglish" if sid.startswith("h") else "English"), []).append(s)
    if not per_engine:
        print("No scores yet.")
        return
    print("\nAverage naturalness score (1-10), higher is better:\n")
    for eng, v in sorted(per_engine.items(), key=lambda kv: -np.mean(kv[1])):
        extra = "".join(f"   {g}: {np.mean(per_group[(eng, g)]):.1f} ({len(per_group[(eng, g)])})"
                        for g in ("English", "Hinglish") if (eng, g) in per_group)
        print(f"  {ENGINES[eng][0]:<36} {np.mean(v):4.1f}   ({len(v)} clips){extra}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reveal", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="list the plan, play nothing")
    args = ap.parse_args()
    if args.reset and SCORES.exists():
        SCORES.unlink()
    if SCORES.exists():
        data = json.loads(SCORES.read_text(encoding="utf-8"))
    else:
        if not AUDIO.exists():
            raise SystemExit("No audio yet: run  python tts_bench.py  first.")
        data = {"plan": build_plan(), "scores": {}}
    if args.reveal:
        reveal(data)
        return 0
    total = sum(len(c) for _, c in data["plan"])
    if args.dry_run:
        print(f"{len(data['plan'])} sentences, {total} clips")
        return 0
    print(__doc__.split("For each sentence")[0].strip().splitlines()[0])
    print("Type 1-10, r = replay, q = quit (progress is saved).\n")
    try:
        for sid, clips in data["plan"]:
            print(f"\n=== Sentence {sid}: \"{SENTENCES[sid]}\"")
            for letter, eng in clips:
                key = f"{sid}{letter}"
                if key in data["scores"]:
                    continue
                path = AUDIO / f"{eng}__{sid}.wav"
                while True:
                    print(f"  clip {letter} ...", end=" ", flush=True)
                    play(path)
                    ans = input("score (1-10, r = replay, q = quit): ").strip().lower()
                    if ans == "r":
                        continue
                    if ans == "q":
                        raise KeyboardInterrupt
                    if ans.isdigit() and 1 <= int(ans) <= 10:
                        data["scores"][key] = int(ans)
                        SCORES.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
                        break
                    print("    please type a number from 1 to 10")
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Run again to continue.")
        return 0
    print("\nAll clips scored.")
    reveal(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
