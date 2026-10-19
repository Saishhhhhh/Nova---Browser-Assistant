"""Starts a slow agent task, then "says" a correction partway through, and checks it cancels the in-flight
step (not just queues the correction to run after it finishes) and then runs the corrected command.

  python -m ash.tests.test_cancel_correction        # real browser, a few cents of Cerebras calls
"""
import sys
import time

from ash import app


def main() -> int:
    import argparse
    args = argparse.Namespace(text=True, script=None, no_sound=True, headless=True, input_device=None,
                              output_device=None, hangover=0.5, min_speech=0.25, cue="none", idle=0, hinglish=False,
                              agent_steps=8, agent_timeout=120.0, start_url="", simulate=True, memory=True)
    runner = app.AsyncRunner()
    loop = app.AppLoop(args, runner)
    browser, loop.router = app.make_router(loop, runner, args)
    loop.plan_client = runner.run(app._make_async_client())
    runner.run(loop.router.run_command("go to books.toscrape.com"))

    # A slow, open-ended, single agent call (deliberately phrased to avoid the planner's multi-step trigger —
    # no comma-before-"and", no "then" — so this exercises a correction cancelling a plain agent call, not a plan).
    # Asks for something comparative across many items so a real agent run takes a few seconds, giving the
    # correction below a real window to interrupt it (not racing a task that might finish in under a second).
    task = ("carefully compare every single book on this entire page one by one and give me a detailed "
            "paragraph explaining which title sounds the most interesting to read and why, considering all "
            "the options before answering")
    t0 = time.perf_counter()
    loop.busy = True
    loop.jobs.put({"kind": "turn", "text": task, "clip": None, "epoch": loop.epoch, "speech_s": 0.0, "wait_ms": 0.0,
                   "hangover": 0.0, "t_trigger": time.perf_counter()})

    # Poll until the agent is actually mid-flight (self.router._agent set), so the correction below has
    # something real to cancel instead of racing a task that might already be done.
    deadline = time.perf_counter() + 15
    while loop.router._agent is None and time.perf_counter() < deadline:
        time.sleep(0.05)
    still_running = loop.router._agent is not None
    correction_text = "No, I meant scroll down"
    print(f"agent running at {time.perf_counter() - t0:.1f} s: {still_running}; saying a correction: {correction_text!r}",
          flush=True)
    from ash.router import is_correction
    assert is_correction(correction_text), "is_correction() should recognise this as a correction"
    loop.cancel_agent()
    job2 = {"kind": "turn", "text": correction_text, "clip": None, "epoch": loop.epoch, "speech_s": 0.0,
            "wait_ms": 0.0, "hangover": 0.0, "t_trigger": time.perf_counter(), "stt_ms": 0.0}
    loop.jobs.put(job2)

    deadline = time.perf_counter() + 30
    while len(loop.records) < 1 and time.perf_counter() < deadline:
        time.sleep(0.05)
    time.sleep(0.3)  # let anything further settle

    print(f"\nRESULT: {len(loop.records)} record(s) written")
    for r in loop.records:
        print(f"  tier={r['tier']:<8} ok={r['ok']} command={r['command'][:60]!r} reply={r['reply'][:80]!r}")
    # A cancelled task produces NO record at all (matching test_cancel.py's established "stopped; no answer
    # spoken" behaviour) — so success here is exactly one record, and it's the corrected "scroll down", not
    # the original long comparison task.
    ok = (still_running and len(loop.records) == 1 and "scroll" in loop.records[0]["command"].lower()
          and loop.records[0]["ok"])
    if ok:
        print("PASS: the correction cancelled the in-flight task (no record for it, same as a plain 'stop') "
              "and the corrected 'scroll down' ran next, successfully, as its own turn")
    else:
        print("FAIL (or the original task finished before the correction landed — see still_running above)")
    try:
        runner.run(loop.plan_client.aclose(), timeout=5)
    except Exception:
        pass
    try:
        runner.run(browser.kill(), timeout=15)
    except Exception:
        pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
