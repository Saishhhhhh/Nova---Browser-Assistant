"""Starts a multi-step PLAN, says "stop" partway through, and checks the plan stops after the current step
instead of running the rest (Phase 1: planner integration, the plan-aware half of cancel_agent()).

  python -m tests.test_cancel_plan        # real browser, a few cents of DeepInfra (plan) + Cerebras (final step) calls
"""
import argparse
import sys
import time

from nova import app


def main() -> int:
    args = argparse.Namespace(text=True, script=None, no_sound=True, headless=True, input_device=None,
                              output_device=None, hangover=0.5, min_speech=0.25, cue="none", idle=0, hinglish=False,
                              agent_steps=8, agent_timeout=120.0, start_url="", simulate=True, memory=True)
    runner = app.AsyncRunner()
    loop = app.AppLoop(args, runner)
    browser, loop.router = app.make_router(loop, runner, args)
    loop.plan_client = runner.run(app._make_async_client())

    # Four steps before the final question, enough real page loads to give "stop" a window to land mid-plan.
    task = ("Go to books.toscrape.com, click travel, go back, click mystery, and tell me the title of the first book")
    t0 = time.perf_counter()
    loop.busy = True
    loop.jobs.put({"kind": "turn", "text": task, "clip": None, "epoch": loop.epoch, "speech_s": 0.0, "wait_ms": 0.0,
                   "hangover": 0.0, "t_trigger": time.perf_counter()})
    time.sleep(3.0)
    t_stop = time.perf_counter()
    print(f"saying stop at {t_stop - t0:.1f} s; plan_active={loop.plan_active}", flush=True)
    loop.cancel_agent()
    while loop.busy:
        time.sleep(0.05)
    t_end = time.perf_counter()

    rec = loop.records[-1] if loop.records else None
    print(f"\nRESULT: stop issued at {t_stop - t0:.1f} s, plan ended {t_end - t_stop:.1f} s later")
    if rec is None:
        print("FAIL: no record written at all")
        return 1
    print(f"  tier={rec['tier']} detail={rec['detail']!r}")
    steps_total = rec["detail"].split("/")[1].split()[0] if "/" in rec["detail"] else "?"
    ran_fewer = rec["detail"].startswith("plan ") and not rec["ok"]
    print("PASS: plan was cut short (did not run all steps) and no final answer was recorded as ok"
          if ran_fewer else "FAIL: plan appears to have run to completion despite 'stop'")
    try:
        runner.run(loop.plan_client.aclose(), timeout=5)
    except Exception:
        pass
    try:
        runner.run(browser.kill(), timeout=15)
    except Exception:
        pass
    return 0 if ran_fewer else 1


if __name__ == "__main__":
    sys.exit(main())
