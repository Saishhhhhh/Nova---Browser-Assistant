"""Experiment 4 benchmark: which VAD, and how long a silence before declaring "you have finished".

  python vad_bench.py                 # everything (about a minute)
  python vad_bench.py --quick         # clean audio only

Runs on the full recordings from Experiment 3 (data/wav/V0..V10.wav, 4 commands each, ~1 s apart),
exactly like a live microphone would be heard: one continuous stream, the VAD has to find each command.
Offline, no API calls. Writes results/vad_bench.json and results/VAD_SUMMARY.md.

Where "the truth" comes from: Experiment 3's energy-based splitter (prepare_dataset.speech_regions), the
same one that cut the clips. It is NOT independent of the Energy detector below, so read that row with
care; check_labels.py plots the boundaries so they can be inspected by eye.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
STT = HERE.parent / "03_Speech_To_Text"
sys.path.insert(0, str(STT))
sys.path.insert(0, str(HERE))

from prepare_dataset import speech_regions  # noqa: E402
from vad_core import SR, frame_scores, make_detector, segment  # noqa: E402

RESULTS = HERE / "results"
PRE_ROLL_S = 0.3                      # audio kept from before the detected start
HANGOVERS = (0.3, 0.5, 0.8)           # silence (s) before declaring the end
DETECTORS = {                         # name -> thresholds to try
    "silero": (0.3, 0.5, 0.7),
    "webrtc0": (0.5,), "webrtc1": (0.5,), "webrtc2": (0.5,), "webrtc3": (0.5,),
    "energy": (9.0, 12.0, 15.0),
}
TRUTH_GAPS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.9, 1.1, 1.4)
CONDITIONS = ("clean", "pink20", "pink10", "pink5", "clicks")


# ----------------------------------------------------------------------------- data

def load_recordings() -> dict:
    """{'V0': int16 array, ...} plus the truth speech regions for V1..V10."""
    manifest = json.loads((STT / "data" / "manifest.json").read_text(encoding="utf-8"))
    expected = {}
    for c in manifest:
        expected[c["source"]] = expected.get(c["source"], 0) + 1
    audio, truth = {}, {}
    for vid in ["V0"] + [f"V{i}" for i in range(1, 11)]:
        sr, x = wavfile.read(STT / "data" / "wav" / f"{vid}.wav")
        assert sr == SR and x.dtype == np.int16
        audio[vid] = x
        if vid == "V0":
            truth[vid] = []
            continue
        # Smallest pause setting that finds the right number of commands. Experiment 3 used the largest
        # that worked, which merged a click or breath into the next command (V5 command 3, 0.65 s early).
        for gap in TRUTH_GAPS:
            regions = speech_regions(x, SR, gap)
            if len(regions) == expected[vid]:
                truth[vid] = regions
                break
        else:
            raise SystemExit(f"{vid}: could not find {expected[vid]} commands; run prepare_dataset.py first")
    return {"audio": audio, "truth": truth}


def speech_rms(x: np.ndarray, regions: list) -> float:
    parts = [x[int(a * SR):int(b * SR)].astype(np.float64) for a, b in regions]
    return float(np.sqrt(np.mean(np.concatenate(parts) ** 2)))


def pink_noise(n: int, rng) -> np.ndarray:
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(len(spec), dtype=np.float64)
    f[0] = 1.0
    out = np.fft.irfft(spec / np.sqrt(f), n)
    return out / np.sqrt(np.mean(out ** 2))


def add_condition(x: np.ndarray, kind: str, ref_rms: float, rng) -> np.ndarray:
    """Return x with noise mixed in. ref_rms is the speech level the noise is set relative to."""
    if kind == "clean":
        return x
    y = x.astype(np.float64)
    if kind.startswith("pink"):
        snr_db = float(kind[4:])
        y += pink_noise(len(x), rng) * ref_rms / 10 ** (snr_db / 20)
    elif kind == "clicks":  # keyboard-like: 6 ms decaying bursts about every 0.7 s, as loud as the speech
        t = rng.exponential(0.7)
        n_burst = int(0.006 * SR)
        env = np.exp(-np.arange(n_burst) / (0.0015 * SR))
        while t < len(x) / SR - 0.1:
            i = int(t * SR)
            y[i:i + n_burst] += rng.standard_normal(n_burst) * env * ref_rms * 1.5
            t += rng.exponential(0.7)
    return np.clip(y, -32768, 32767).astype(np.int16)


# ----------------------------------------------------------------------------- scoring

def overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def evaluate(utts: list, truth: list) -> dict:
    """Compare detected utterances with the real commands of one recording.

    An utterance's audio window is [start - pre-roll, trigger]. For each real command:
      ok      exactly one window covers it, and covers >= 97% of its speech
      clipped exactly one window, but the beginning is cut (detected too late)
      split   two or more windows touch it (the VAD declared the end in the middle of the command)
      merged  its window also touches a different command (two commands in one clip)
      missed  no window touches it
    Utterances that touch no command at all (+- 0.25 s) are false alarms.
    """
    wins = [(u["start"] - PRE_ROLL_S, u["trigger"], u) for u in utts]
    res = {"ok": 0, "clipped": 0, "split": 0, "merged": 0, "missed": 0, "false_alarms": 0,
           "start_lag": [], "end_latency": [], "problems": []}
    for k, (a, b) in enumerate(truth):
        hits = [i for i, (w0, w1, _) in enumerate(wins) if overlap(w0, w1, a, b) > 0]
        if not hits:
            res["missed"] += 1
            res["problems"].append((k, "missed"))
            continue
        if len(hits) >= 2:
            res["split"] += 1
            res["problems"].append((k, "split"))
            continue
        w0, w1, u = wins[hits[0]]
        if any(j != k and overlap(w0, w1, c, d) > 0 for j, (c, d) in enumerate(truth)):
            res["merged"] += 1
            res["problems"].append((k, "merged"))
            continue
        if overlap(w0, w1, a, b) / (b - a) >= 0.97:
            res["ok"] += 1
        else:
            res["clipped"] += 1
            res["problems"].append((k, "clipped"))
        res["start_lag"].append(u["start"] - a)
        res["end_latency"].append(u["trigger"] - b)
    for u in utts:
        if not any(overlap(u["start"], u["speech_end"], a - 0.25, b + 0.25) > 0 for a, b in truth):
            res["false_alarms"] += 1
    return res


def pct(values: list, q: float):
    return round(float(np.percentile(values, q)) * 1000) if values else None


# ----------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="clean audio only")
    args = ap.parse_args()
    data = load_recordings()
    audio, truth = data["audio"], data["truth"]
    n_truth = sum(len(v) for v in truth.values())
    ref = {vid: speech_rms(audio[vid], truth[vid]) for vid in audio if truth[vid]}
    ref["V0"] = ref["V1"]
    conditions = ("clean",) if args.quick else CONDITIONS
    rng = np.random.default_rng(7)

    # 1. per-frame scores: the slow part, done once per (condition, detector, recording)
    scores = {}
    t0 = time.perf_counter()
    for cond in conditions:
        noisy = {vid: add_condition(audio[vid], cond, ref[vid], rng) for vid in audio}
        for dname in DETECTORS:
            det = make_detector(dname)
            for vid, x in noisy.items():
                scores[(cond, dname, vid)] = frame_scores(det, x)
        print(f"scored {cond:<7} ({time.perf_counter() - t0:.0f} s)", flush=True)

    # 2. real-time cost of one frame, per detector (on clean V6, the longest file)
    cost = {}
    for dname in DETECTORS:
        det = make_detector(dname)
        det.reset()
        x = audio["V6"][: det.frame * 600]
        t = time.perf_counter()
        for i in range(600):
            det.score(x[i * det.frame:(i + 1) * det.frame])
        ms = (time.perf_counter() - t) / 600 * 1000
        cost[dname] = {"ms_per_frame": round(ms, 3), "frame_ms": det.frame / SR * 1000,
                       "cpu_share_of_one_core": round(ms / (det.frame / SR * 1000), 4)}

    # 3. every setting, every condition
    rows = []
    frame_s = {d: make_detector(d).frame_s for d in DETECTORS}
    for dname, thresholds in DETECTORS.items():
        for thr in thresholds:
            for hang in HANGOVERS:
                row = {"detector": dname, "threshold": thr, "hangover_s": hang, "conditions": {}}
                for cond in conditions:
                    agg = {"ok": 0, "clipped": 0, "split": 0, "merged": 0, "missed": 0, "false_alarms": 0,
                           "start_lag": [], "end_latency": [], "problems": {}}
                    for vid in audio:
                        utts = segment(scores[(cond, dname, vid)], frame_s[dname], thr, hang)
                        r = evaluate(utts, truth[vid])
                        for key in ("ok", "clipped", "split", "merged", "missed", "false_alarms"):
                            agg[key] += r[key]
                        agg["start_lag"] += r["start_lag"]
                        agg["end_latency"] += r["end_latency"]
                        if r["problems"]:
                            agg["problems"][vid] = r["problems"]
                    agg["start_lag_ms_median"] = pct(agg["start_lag"], 50)
                    agg["start_lag_ms_p95"] = pct(agg["start_lag"], 95)
                    agg["end_latency_ms_median"] = pct(agg["end_latency"], 50)
                    agg["end_latency_ms_p95"] = pct(agg["end_latency"], 95)
                    del agg["start_lag"], agg["end_latency"]
                    row["conditions"][cond] = agg
                rows.append(row)

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "vad_bench.json").write_text(
        json.dumps({"n_commands": n_truth, "pre_roll_s": PRE_ROLL_S, "cost": cost, "rows": rows},
                   indent=1), encoding="utf-8")
    write_summary(rows, cost, n_truth, conditions)
    return 0


def write_summary(rows: list, cost: dict, n_truth: int, conditions) -> None:
    lines = [f"# VAD results ({n_truth} commands in 10 recordings + 1 silent recording)", "",
             "Per setting: commands handled **ok** out of 40 (clean audio), commands **split** (end declared mid-command), "
             "**merged** (two commands in one clip), **clipped** (start cut), **missed**, and **false alarms** (speech reported "
             "where nobody spoke, including the silent recording). `end wait` = time from the real end of speech to "
             "the VAD declaring it (median / 95th percentile). `start lag` = how late the start was detected.", "",
             "| Detector | thr | hangover | ok | split | merged | clipped | missed | false alarms | end wait (ms) | start lag (ms) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        c = r["conditions"]["clean"]
        lines.append(f"| {r['detector']} | {r['threshold']} | {int(r['hangover_s'] * 1000)} ms | {c['ok']}/{n_truth} | {c['split']} | "
                     f"{c['merged']} | {c['clipped']} | {c['missed']} | {c['false_alarms']} | "
                     f"{c['end_latency_ms_median']} / {c['end_latency_ms_p95']} | {c['start_lag_ms_median']} |")
    if len(conditions) > 1:
        lines += ["", "## With noise", "", "ok out of 40 / false alarms, per condition. `pinkN` = pink (fan-like) noise N dB "
                  "below the speech level, so pink5 is loud noise. `clicks` = keyboard-like bursts as loud as speech.", "",
                  "| Detector | thr | hangover | " + " | ".join(conditions) + " |",
                  "|---|---|---|" + "---|" * len(conditions)]
        for r in rows:
            cells = [f"{r['conditions'][k]['ok']} / {r['conditions'][k]['false_alarms']}" for k in conditions]
            lines.append(f"| {r['detector']} | {r['threshold']} | {int(r['hangover_s'] * 1000)} ms | " + " | ".join(cells) + " |")
    lines += ["", "## Cost per frame (one CPU core)", "", "| Detector | frame | time per frame | share of real time |", "|---|---|---|---|"]
    for d, v in cost.items():
        lines.append(f"| {d} | {v['frame_ms']:.0f} ms | {v['ms_per_frame']} ms | {v['cpu_share_of_one_core'] * 100:.1f}% |")
    (RESULTS / "VAD_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
