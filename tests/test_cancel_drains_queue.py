"""Reproduces the live session's problem: several things said while busy pile up in the queue, then a
"stop" should drop that backlog instead of making you sit through each one, one by one.

  python -m tests.test_cancel_drains_queue        # real browser, a few cents of Cerebras calls
"""
import argparse
import sys
import time

from jarvis import app


def main() -> int:
    args = argparse.Namespace(text=True, script=None, no_sound=True, headless=True, input_device=None,
                              output_device=None, hangover=0.5, min_speech=0.25, cue="none", idle=0, hinglish=False,
                              agent_steps=8, agent_timeout=120.0, start_url="", simulate=True, memory=True)
    runner = app.AsyncRunner()
    loop = app.AppLoop(args, runner)
    browser, loop.router = app.make_router(loop, runner, args)
    loop.plan_client = runner.run(app._make_async_client())
    runner.run(loop.router.run_command("go to books.toscrape.com"))

    task = ("carefully compare every single book on this entire page one by one and give me a detailed "
            "paragraph explaining which title sounds the most interesting to read and why, considering all "
            "the options before answering")
    t0 = time.perf_counter()
    loop.busy = True
    loop.jobs.put({"kind": "turn", "text": task, "clip": None, "epoch": loop.epoch, "speech_s": 0.0, "wait_ms": 0.0,
                   "hangover": 0.0, "t_trigger": time.perf_counter()})

    deadline = time.perf_counter() + 15
    while loop.router._agent is None and time.perf_counter() < deadline:
        time.sleep(0.05)
    still_running = loop.router._agent is not None
    print(f"agent running at {time.perf_counter() - t0:.1f} s: {still_running}", flush=True)

    # Simulate three things said while busy, like the live session: two irrelevant utterances that just
    # queue, then a real "stop" that should drop them both instead of letting them run first.
    for extra_text in ("Hold hold hold stop stop stop stop.", "github.com/saish. Saish should have 6H."):
        loop.jobs.put({"kind": "turn", "text": extra_text, "clip": None, "epoch": loop.epoch, "speech_s": 0.0,
                       "wait_ms": 0.0, "hangover": 0.0, "t_trigger": time.perf_counter(), "stt_ms": 0.0})
    print(f"queued 2 extra commands; queue size now: {loop.jobs.qsize()}", flush=True)

    print("saying 'Stop.'", flush=True)
    loop.cancel_agent()
    print(f"queue size right after cancel: {loop.jobs.qsize()} (should be 0)", flush=True)

    job_final = {"kind": "turn", "text": "scroll down", "clip": None, "epoch": loop.epoch, "speech_s": 0.0,
                "wait_ms": 0.0, "hangover": 0.0, "t_trigger": time.perf_counter(), "stt_ms": 0.0}
    loop.jobs.put(job_final)
    t_after_cancel = time.perf_counter()

    deadline = time.perf_counter() + 20
    while len(loop.records) < 1 and time.perf_counter() < deadline:
        time.sleep(0.05)
    time.sleep(0.3)

    print(f"\nRESULT: {len(loop.records)} record(s) written, the one after 'stop' took "
          f"{(time.perf_counter() - t_after_cancel):.1f} s to run (should be fast, not stuck behind a backlog)")
    for r in loop.records:
        print(f"  tier={r['tier']:<8} ok={r['ok']} command={r['command'][:60]!r} reply={r['reply'][:80]!r}")
    ok = (still_running and len(loop.records) == 1 and "scroll" in loop.records[0]["command"].lower()
          and loop.records[0]["ok"] and (time.perf_counter() - t_after_cancel) < 10)
    print("PASS: the two queued distractions were dropped; only 'scroll down' ran, and quickly"
          if ok else "FAIL: see records above")
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
