"""Does a VAD-cut clip transcribe as well as the clip cut by hand? (Experiment 4, last check)

  python vad_to_stt.py            # real ElevenLabs calls: ~140 short clips, well under a cent each

Cuts the clean recordings (V1..V9, 36 commands; V10 is Hinglish and left out, as in Experiment 3) with a few
VAD settings, sends every clip to ElevenLabs `scribe_v2` and scores it like Experiment 3 did. The clip is exactly
what the live tool would send: from `pre-roll` before the detected start to the moment the end is declared.
The comparison line is Experiment 3's result on the hand-cut clips for the same engine.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import numpy as np
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "03_Speech_To_Text"))
import stt_bench as stt  # noqa: E402
from vad_bench import PRE_ROLL_S, load_recordings, overlap  # noqa: E402
from vad_core import SR, frame_scores, make_detector, segment  # noqa: E402

CONFIGS = [("silero", 0.5, 0.3), ("silero", 0.5, 0.5), ("webrtc3", 0.5, 0.5), ("energy", 12.0, 0.5)]
VIDS = [f"V{i}" for i in range(1, 10)]


def clip_wav(pcm: np.ndarray) -> bytes:
    import io
    buf = io.BytesIO()
    wavfile.write(buf, SR, pcm)
    return buf.getvalue()


async def main() -> int:
    data = load_recordings()
    manifest = json.loads((stt.DATA / "manifest.json").read_text(encoding="utf-8"))
    script = {c["id"]: c["text"] for c in manifest}
    key = os.getenv("ELEVENLABS_API_KEY")
    if not stt.have_key("ELEVENLABS_API_KEY"):
        raise SystemExit("ELEVENLABS_API_KEY is not set in .env")
    sem = asyncio.Semaphore(3)

    async def send(client, pcm):
        async with sem:
            return await stt.timed_call(stt.elevenlabs_batch, client, key, clip_wav(pcm), "V1", None, False)

    summary = []
    async with httpx.AsyncClient(timeout=60) as client:
        for dname, thr, hang in CONFIGS:
            det = make_detector(dname)
            jobs, meta = [], []   # one job per detected utterance
            wrong_count = 0
            for vid in VIDS:
                x, truth = data["audio"][vid], data["truth"][vid]
                utts = segment(frame_scores(det, x), det.frame_s, thr, hang)
                wrong_count += len(utts) != len(truth)
                for u in utts:
                    a, b = max(0.0, u["start"] - PRE_ROLL_S), u["trigger"]
                    clip = x[int(a * SR):int(b * SR)]
                    k = max(range(len(truth)), key=lambda j: overlap(a, b, *truth[j]))
                    if overlap(a, b, *truth[k]) == 0:
                        continue          # a false alarm: sent nowhere (the live tool would send it)
                    jobs.append(send(client, clip))
                    meta.append((vid, k, b - a))
            outs = await asyncio.gather(*jobs, return_exceptions=True)
            hyp, secs, errors = {}, [], 0
            for (vid, k, dur), out in zip(meta, outs):
                if isinstance(out, Exception):
                    errors += 1
                    continue
                hyp.setdefault(f"{vid}_{k + 1}", []).append(out[0])
                secs.append(dur)
            edits = words = exact = intent = 0
            for cid in (f"{v}_{k}" for v in VIDS for k in range(1, 5)):
                row = stt.score({"text": script[cid]}, " ".join(hyp.get(cid, [])))
                edits += row["edits"]; words += row["ref_words"]; exact += row["exact"]; intent += row["intent"]
            res = {"detector": dname, "threshold": thr, "hangover_s": hang,
                   "files_with_wrong_command_count": wrong_count, "wer_pct": round(100 * edits / words, 1),
                   "exact_pct": round(100 * exact / 36), "intent_pct": round(100 * intent / 36),
                   "clips_sent": len(meta), "mean_clip_s": round(float(np.mean(secs)), 2), "errors": errors}
            summary.append(res)
            print(f"{dname:<8} thr {thr:<5} hangover {int(hang * 1000)} ms  WER {res['wer_pct']:>4}%  exact {res['exact_pct']}%  "
                  f"intent {res['intent_pct']}%  clips {len(meta)}  mean clip {res['mean_clip_s']} s  errors {errors}", flush=True)

    base = json.loads((stt.RESULTS / "stt_batch_elevenlabs.json").read_text(encoding="utf-8"))["rows"]
    core = [r for r in base if r["kind"] == "clip" and not r["id"].startswith("V10")]
    b = {"wer_pct": round(100 * sum(r["edits"] for r in core) / sum(r["ref_words"] for r in core), 1),
         "exact_pct": round(100 * sum(r["exact"] for r in core) / len(core)),
         "intent_pct": round(100 * sum(r["intent"] for r in core) / len(core))}
    print(f"hand-cut clips (Experiment 3, same engine): WER {b['wer_pct']}%  exact {b['exact_pct']}%  intent {b['intent_pct']}%")
    (HERE / "results" / "vad_to_stt.json").write_text(json.dumps({"hand_cut": b, "vad_cut": summary}, indent=1),
                                                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
