"""Starts a long agent task, says "stop" 4 s in, and checks the agent stops promptly and nothing is announced.

  python test_cancel.py        # real browser, a few cents of Cerebras calls
"""
import argparse
import sys
import threading
import time

import app


def main() -> int:
    args = argparse.Namespace(text=True, script=None, no_sound=True, headless=True, input_device=None,
                              output_device=None, hangover=0.5, min_speech=0.25, cue="none", idle=0, hinglish=False,
                              agent_steps=8, agent_timeout=120.0, start_url="", simulate=True, memory=True)
    runner = app.AsyncRunner()
    loop = app.AppLoop(args, runner)
    browser, loop.router = app.make_router(loop, runner, args)
    runner.run(loop.router.run_command("go to books.toscrape.com"))

    task = "find every book on this page with a price under 20 pounds, open each one, and list its title and rating"
    t0 = time.perf_counter()
    loop.busy = True
    loop.jobs.put({"kind": "turn", "text": task, "clip": None, "epoch": loop.epoch, "speech_s": 0.0, "wait_ms": 0.0,
                   "hangover": 0.0, "t_trigger": time.perf_counter()})
    time.sleep(4.0)
    t_stop = time.perf_counter()
    print(f"saying stop at {t_stop - t0:.1f} s; agent running: {loop.slow_running}", flush=True)
    loop.cancel_agent()
    while loop.busy:
        time.sleep(0.05)
    t_end = time.perf_counter()
    print(f"\nRESULT: the command ended {t_end - t_stop:.1f} s after 'stop' (task would otherwise run up to 120 s); "
          f"records written: {len(loop.records)} (0 expected: no answer is spoken after a stop)")
    try:
        runner.run(browser.kill(), timeout=15)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
