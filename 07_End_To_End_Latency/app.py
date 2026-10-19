"""Experiment 7: the first runnable version of the app, with every stage timed.

  python app.py                              # voice: microphone -> Silero -> Sarvam -> router -> browser -> Phoebe
  python app.py --text                       # type commands instead of speaking (no microphone)
  python app.py --script commands.txt        # run a list of commands automatically (one per line), then print the waterfall
  python app.py --no-sound --script commands.txt   # same, without audio output

What happens to each command (the "waterfall"):
   you stop speaking -> silence wait (VAD) -> transcript (Sarvam) -> router (rules, then one short model call, then
   the full browser agent) -> a spoken reply (Deepgram Phoebe)
If the router has to start the slow browser agent, "On it." is spoken at once so you are not left in silence.
Everything is timed from the moment you stopped speaking. A JSON waterfall is written to results/.

A request that joins several actions ("go to Amazon, search for MSI monitors, and tell me the cheapest one") is
split into steps by the planner (Experiment 8, Gemma) instead of being handed whole to the agent. Each step runs
through the router and its own reply is spoken ("Opened amazon.com." -> "Searched for MSI monitors." -> the
answer). A single command skips the planner entirely (Exp 8 found planning is not a speed-up for one action).
Say "stop" at any point to cancel a plan or a slow agent step.

Replies are informative, not "Done." for everything: "Opened Travel.", "Scrolled down.", "Clicked the second
result." (dom_fastpath's own natural-language reply for whatever it actually did, Phase 1 of the plan).

REAL API CALLS and a real browser: DeepInfra Gemma for the model step and the planner, Cerebras for the agent,
Sarvam and Deepgram for speech. Voice mode needs HEADPHONES (see Experiment 6). Keys 1 2 3 / 4 5 6 / q work as
in Experiment 6.
"""
import argparse
import asyncio
import datetime
import json
import os
import queue
import re
import statistics
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for sub in ("06_Turn_Taking", "02_Reasoning_and_Routing", "01_Browser Automation"):
    sys.path.insert(0, str(ROOT / sub))

import httpx  # noqa: E402

import voice_loop as vl  # noqa: E402
from dom_fastpath import parse_command  # noqa: E402
from memory import COMPARE_QUESTION, ConversationMemory, compare_from_scratchpad, needs_memory  # noqa: E402
from planner import looks_multi_step, parse_step, plan, replan_after_failure  # noqa: E402
from router import QUESTION, RouterResult, clean_command, is_correction  # noqa: E402
from voice_loop import Loop, mic_source, transcribe  # noqa: E402

ACK = "On it."
STILL = "Still working on it."
HEARTBEAT_FIRST_S, HEARTBEAT_EVERY_S = 12.0, 15.0
CANCEL = re.compile(r"^(?:stop|cancel|never mind|nevermind|forget it|abort|halt|enough)(?![a-z])", re.I)


class AsyncRunner:
    """browser-use is asynchronous; the voice side is threads. This runs one asyncio loop in its own thread."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def run(self, coro, timeout=None):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)


class AppLoop(Loop):
    """The Experiment 6 voice loop, with the router in place of the canned replies."""

    def __init__(self, args, runner):
        super().__init__(args)
        self.runner = runner
        self.router = None        # set once the browser is up
        self.records = []
        self._cur = None
        self.slow_running = False   # a command is going through the slow path (model step or agent)
        self.cancelled = False
        self.pending = None         # (verb, time) after "Click what?": the next words complete the command
        self.plan_client = None     # httpx.AsyncClient for planner.plan(), set once the browser/router are up
        self.plan_active = False    # a multi-step plan is currently running (set for its whole duration, not
        self.plan_cancelled = False  # just the current step), so "stop" cancels the whole plan, not one step
        self.memory = ConversationMemory()   # Phase 2: recent turns + scratchpad, carried across the session

    # --- turn-taking rules specific to the app
    def barge_applies(self) -> bool:
        # speech only interrupts the assistant's own voice; while the browser works it is a new command or "stop"
        return self.speaking or self.player.pending_s() > 0

    def interrupt(self, why: str, heard_ms: float) -> None:
        if self.slow_running:
            self.player.stop()      # silence "On it." / "Still working", but keep the command running
            return
        super().interrupt(why, heard_ms)

    def submit(self, job: dict) -> None:
        if self.slow_running and job["kind"] == "turn" and job.get("text") is None:
            threading.Thread(target=self._while_busy, args=(job,), daemon=True).start()
        else:
            self.jobs.put(job)

    def _while_busy(self, job: dict) -> None:
        """You spoke while the browser is working: "stop" cancels outright; a correction ("no, I meant...",
        "actually...") also cancels the in-flight step — rather than letting a possibly wrong-direction task
        run to completion first — and then queues the corrected command to run next; anything else just queues."""
        try:
            text, ms = transcribe(self.http, job["clip"], self.args.hinglish)
        except Exception as e:
            self.say(f"  !! {type(e).__name__}: {str(e)[:150]}")
            return
        heard = clean_command(text)
        if CANCEL.match(heard):
            self.say(f"  (heard \"{text.strip()}\" -> stop)")   # otherwise a cancel leaves no trace of what triggered it
            self.cancel_agent()
            return
        if not text.strip():
            return
        if is_correction(text):
            self.say(f"  (heard a correction: \"{text.strip()}\"; cancelling the current step)")
            self.cancel_agent()
        job["text"], job["stt_ms"] = text, ms
        self.say(f"  (heard \"{text.strip()}\" while working; it will run next)")
        self.jobs.put(job)

    def _drain_queue(self) -> int:
        """Remove anything waiting in the job queue that hasn't started yet. Called on every cancel, so saying
        "stop" (or a correction) doesn't leave a backlog of other "heard while busy" commands to grind through
        one by one first — found live: three things said in a row while frustrated with a slow task meant
        sitting through all three, one after another, each its own slow round trip, before getting a response."""
        n = 0
        while True:
            try:
                self.jobs.get_nowait()
                n += 1
            except queue.Empty:
                break
        return n

    def cancel_agent(self) -> None:
        dropped = self._drain_queue()
        extra = f", dropped {dropped} queued command(s)" if dropped else ""
        stopped_agent = self.router.cancel()
        if self.plan_active:
            # the running agent step (if any) will stop now; a quick rules step cannot be interrupted mid-click,
            # so plan_cancelled makes the loop break as soon as the current step finishes
            self.plan_cancelled = True
            self.cancelled = True
            self.say("  >> stop: cancelling the plan" + ("" if stopped_agent else " (current step will finish first)") + extra)
            threading.Thread(target=self._speak, args=("Okay, stopping.", self.epoch, {}), daemon=True).start()
            return
        if not stopped_agent:
            self.say(f"  (nothing to stop{extra})")
            return
        self.cancelled = True
        self.say("  >> stop: the agent will stop after its current step" + extra)
        threading.Thread(target=self._speak, args=("Okay, stopping.", self.epoch, {}), daemon=True).start()

    # called from the router's thread the moment it falls through to the slow agent
    def on_agent_start(self) -> None:
        cur = self._cur
        if not cur or cur.get("ack_thread"):
            return
        self.slow_running = True

        def beat():                      # a short spoken sign of life every 15 s, so a long run is never silent
            waited = 0.0
            while not cur.get("done") and not self.cancelled:
                time.sleep(0.5)
                waited += 0.5
                if waited >= HEARTBEAT_FIRST_S and (waited - HEARTBEAT_FIRST_S) % HEARTBEAT_EVERY_S < 0.5                         and not self.speaking and self.player.pending_s() == 0:
                    self._speak(STILL, cur["epoch"], {})

        threading.Thread(target=beat, daemon=True).start()

        def go():
            def mark(now, ms):
                cur["ack_ms"] = (now - cur["t_speech_end"]) * 1000
            self._speak(ACK, cur["epoch"], {}, on_first_audio=mark)

        cur["ack_thread"] = threading.Thread(target=go, daemon=True)
        cur["ack_thread"].start()

    def _handle(self, job: dict) -> None:
        if job["epoch"] != self.epoch:
            return
        if job["kind"] == "say":
            self._speak(job["text"], job["epoch"], {})
            return
        if job.get("text") is not None:            # typed command, or one transcribed while the browser was busy
            text, stt_ms = job["text"], float(job.get("stt_ms", 0.0))
        else:
            text, stt_ms = transcribe(self.http, job["clip"], self.args.hinglish)
        if job["epoch"] != self.epoch:
            self.say(f"  (you spoke again; dropped \"{text}\")")
            return
        if not text.strip():
            self.say("  (nothing recognised)")
            return
        if self.pending and time.time() - self.pending[1] < 10:
            # the previous command was just a verb ("Click."); these words are probably what it should act on
            cand = clean_command(text)
            if parse_command(cand).kind == "unknown" and not QUESTION.match(cand):
                text = f"{self.pending[0]} {cand}"
                self.say(f"  (joined with \"{self.pending[0]}\": \"{text}\")")
        self.pending = None
        if self.plan_client is not None and looks_multi_step(text):
            self._handle_plan(text, stt_ms, job)
            return
        self._run_single(text, stt_ms, job)

    def _run_single(self, text: str, stt_ms: float, job: dict) -> None:
        t_end = job["t_trigger"] - job["wait_ms"] / 1000
        # If this job sat behind a previous turn (it finished VAD+transcription, but the single worker thread was
        # still busy with the last command), that queue wait is real time the user felt but the silence/transcript/
        # browser/voice breakdown below doesn't otherwise show (found live: a 4.3 s breakdown printed next to a
        # genuine 17 s wait, with nothing accounting for the other 13 s).
        queued_ms = max(0.0, (time.perf_counter() - t_end) * 1000 - job["wait_ms"] - stt_ms)
        cur = {"epoch": job["epoch"], "t_speech_end": t_end, "ack_ms": None}
        self._cur = cur
        # Phase 2: a command that points at something outside itself ("the cheaper one", "go back to that") gets
        # the recent conversation and any remembered facts appended, so the agent (which sees the whole string as
        # its task) has something to resolve the reference against. Appended AFTER the real command, not before,
        # so the rules and the QUESTION check (which only look at the start of the string) see it unchanged.
        to_run = text
        if self.args.memory and len(text.split()) > 2 and needs_memory(text):  # leave short fragments ("that")
                                                             # to the router's own clarify/vague-command handling
            ctx = self.memory.context_block()
            if ctx:
                to_run = f"{text} ({ctx})"
                self.say(f"  (added memory: {ctx[:160]})")
        t_route = time.perf_counter()
        try:
            res = self.runner.run(self.router.run_command(to_run))
        finally:
            cur["done"] = True
            self.slow_running = False
        route_ms = (time.perf_counter() - t_route) * 1000
        if cur.get("ack_thread"):
            cur["ack_thread"].join()               # let "On it." finish before the answer
        if self.cancelled:
            self.cancelled = False
            self.say("  (stopped; no answer spoken)")
            return
        if res.tier == "chat":
            if res.reply:
                self._speak(res.reply, job["epoch"], {})
            else:
                self.say(f"  (small talk: \"{text.strip()}\"; nothing to do)")
            return
        if res.tier == "clarify":
            self.pending = (re.sub(r"[^a-z ]", "", res.command.lower()).strip(), time.time())
        if job["epoch"] != self.epoch:
            self.say("  (you spoke again; dropped the answer)")
            return
        n = self._next_turn()
        meta = {"turn": n, "speech_s": round(job["speech_s"], 2), "text": text, "reply": res.reply,
                "stt_ms": round(stt_ms), "silence_wait_ms": round(job["wait_ms"]), "hangover_s": job["hangover"],
                "route_ms": round(route_ms), "tier": res.tier, "t_speech_end": t_end}
        self._speak(res.reply, job["epoch"], meta)
        self.memory.add_turn(text, res.reply, res.ok)
        done_ms = (time.perf_counter() - t_end) * 1000
        first_sound = min(x for x in (cur["ack_ms"], meta.get("felt_ms")) if x is not None) if (cur["ack_ms"] or meta.get("felt_ms")) else None
        rec = {"turn": n, "command": text, "tier": res.tier, "ok": res.ok, "silence_wait_ms": meta["silence_wait_ms"],
               "stt_ms": meta["stt_ms"], "queued_ms": round(queued_ms), "fast_path_ms": round(res.fast_ms),
               "route_ms": meta["route_ms"],
               "agent_steps": res.agent_steps, "ack_first_sound_ms": round(cur["ack_ms"]) if cur["ack_ms"] else None,
               "answer_first_sound_ms": meta.get("felt_ms"), "first_sound_ms": round(first_sound) if first_sound else None,
               "finished_ms": round(done_ms), "reply": res.reply[:200], "detail": res.detail[:200]}
        self.records.append(rec)
        ack = f", \"On it.\" at {cur['ack_ms'] / 1000:.2f} s" if cur["ack_ms"] else ""
        queued = f"queued {queued_ms / 1000:.2f} | " if queued_ms > 100 else ""  # only shown when it actually happened
        self.say(f"          waterfall: {queued}silence {rec['silence_wait_ms'] / 1000:.2f} | transcript {rec['stt_ms'] / 1000:.2f} | "
                 f"browser step {rec['route_ms'] / 1000:.2f} [{rec['tier']}{', ' + str(rec['agent_steps']) + ' steps' if rec['agent_steps'] else ''}] | "
                 f"voice {meta.get('tts_first_audio_ms', 0) / 1000:.2f}   ->  first sound {((rec['first_sound_ms'] or 0) / 1000):.2f} s{ack}, "
                 f"answer {(rec['answer_first_sound_ms'] or 0) / 1000:.2f} s, finished {rec['finished_ms'] / 1000:.2f} s")

    def _handle_plan(self, text: str, stt_ms: float, job: dict) -> None:
        """A request that joins several actions ("go to Amazon, search for X, tell me the cheapest"): split it
        with the planner (Exp 8), then run each step through the router in turn, speaking its own reply after
        each one. A failed step stops the plan there, saying how far it got, instead of guessing at the rest.
        Every step's reply is already natural language (dom_fastpath's `spoken` field, wired in Phase 1), so no
        separate narration text is needed here — the router's own reply for "clicked the second result" already
        names what it actually clicked.
        """
        t_end = job["t_trigger"] - job["wait_ms"] / 1000
        queued_ms = max(0.0, (time.perf_counter() - t_end) * 1000 - job["wait_ms"] - stt_ms)  # see _run_single
        cur = {"epoch": job["epoch"], "t_speech_end": t_end, "ack_ms": None}
        self._cur = cur
        try:
            steps, plan_ms, err = self.runner.run(plan(self.plan_client, text))
        except Exception as e:
            steps, plan_ms, err = None, 0.0, f"{type(e).__name__}: {e}"
        if not steps:
            cur["done"] = True
            self.say(f"  (planning failed: {err}; running it as one command instead)")
            self._run_single(text, stt_ms, job)
            return
        self.say(f"  (plan, {round(plan_ms)} ms, {len(steps)} steps: " + "  ->  ".join(steps) + ")")
        self.slow_running = True
        self.plan_active = True
        self.plan_cancelled = False
        steps = list(steps)             # a mutable copy: replan_after_failure can splice in a replacement tail
        final_res, n_done, agent_steps_total, replanned = None, 0, 0, False
        t_steps = time.perf_counter()
        try:
            i = 0
            while i < len(steps):
                step = steps[i]
                i += 1
                if job["epoch"] != self.epoch:
                    self.say("  (you spoke again; plan dropped)")
                    return
                kind, _ = parse_step(step)
                # a comparison/verdict question ("which is cheaper") is answered from facts earlier "ask" steps
                # already found, not by reading whatever page the browser happens to be on now (Phase 2)
                if self.args.memory and kind == "ask" and COMPARE_QUESTION.search(step) and self.memory.scratchpad:
                    answer, cmp_ms = self.runner.run(compare_from_scratchpad(self.plan_client, step, self.memory.scratchpad))
                    res = RouterResult(step, "compare", True, answer, detail="answered from remembered facts",
                                       fast_ms=cmp_ms, total_ms=cmp_ms)
                else:
                    res = self.runner.run(self.router.run_command(step))
                    if self.args.memory and kind == "ask" and res.ok:
                        self.memory.remember(step, res.reply)
                final_res, n_done = res, i
                agent_steps_total += res.agent_steps
                if self.plan_cancelled:
                    self.say(f"  (plan stopped after step {i}/{len(steps)}: \"{step}\")")
                    return
                if not res.ok:
                    self.say(f"  (plan step {i}/{len(steps)} failed: \"{step}\" -> {res.detail[:120]})")
                    if self.args.memory and not replanned:
                        replanned = True
                        self.say("  (trying a replacement for the rest of the plan once)")
                        new_tail, replan_ms, replan_err = self.runner.run(replan_after_failure(
                            self.plan_client, text, steps[:i - 1], step, res.detail[:200], steps[i:]))
                        if new_tail:
                            self.say(f"  (replan, {round(replan_ms)} ms: " + "  ->  ".join(new_tail) + ")")
                            steps[i:] = new_tail
                            continue
                        self.say(f"  (no usable replacement: {replan_err or 'the model suggested nothing'})")
                    self._speak(f"I got to step {i} of {len(steps)}, but then: {res.reply}", job["epoch"], {})
                    return
                self.say(f"  (step {i}/{len(steps)} ok [{res.tier}]: \"{step}\" -> {res.reply[:150]!r})")
                self._speak(res.reply, job["epoch"], {})
        finally:
            self.slow_running = False
            self.plan_active = False
            self.plan_cancelled = False
            self.cancelled = False
            cur["done"] = True
            route_ms = (time.perf_counter() - t_steps) * 1000
            n = self._next_turn()
            ok = bool(final_res is not None and final_res.ok and n_done == len(steps))
            self.memory.add_turn(text, final_res.reply if final_res else "", ok)
            rec = {"turn": n, "command": text, "tier": "plan", "ok": ok, "replanned": replanned,
                   "silence_wait_ms": round(job["wait_ms"]), "stt_ms": round(stt_ms or 0.0),
                   "queued_ms": round(queued_ms), "fast_path_ms": round(plan_ms), "route_ms": round(route_ms),
                   "agent_steps": agent_steps_total,
                   "ack_first_sound_ms": None, "answer_first_sound_ms": None, "first_sound_ms": None,
                   "finished_ms": round((time.perf_counter() - t_end) * 1000),
                   "reply": (final_res.reply[:200] if final_res else ""),
                   "detail": f"plan {n_done}/{len(steps)} steps: {steps}"[:200]}
            self.records.append(rec)
            queued = f"queued {queued_ms / 1000:.2f} s, " if queued_ms > 100 else ""
            self.say(f"          waterfall: {queued}plan call {plan_ms / 1000:.2f} s, {n_done}/{len(steps)} steps run, "
                     f"finished {rec['finished_ms'] / 1000:.2f} s")


def make_router(loop: AppLoop, runner: AsyncRunner, args):
    from browser_use import Browser
    from config import EXTRACTION_MODEL, EXTRACTION_PROVIDER, get_browser_use_llm
    from dom_fastpath import make_picker_from_env
    from router import CommandRouter

    kwargs = dict(headless=args.headless, no_viewport=True, keep_alive=True)
    if not args.headless:
        kwargs.update(window_position={"width": 0, "height": 0}, window_size={"width": 1536, "height": 864})
    browser = Browser(**kwargs)
    runner.run(browser.start())
    picker = make_picker_from_env()
    router = CommandRouter(
        browser, picker=picker, agent_llm=get_browser_use_llm("cerebras"),
        extraction_llm=get_browser_use_llm(EXTRACTION_PROVIDER, EXTRACTION_MODEL) if EXTRACTION_PROVIDER else None,
        agent_max_steps=args.agent_steps, agent_timeout=args.agent_timeout, on_agent_start=loop.on_agent_start)
    print(f"browser open. fast-path model: {picker.provider}/{picker.model} (limit {picker.timeout:.0f} s); "
          f"agent: cerebras, up to {args.agent_steps} steps / {args.agent_timeout:.0f} s", flush=True)
    return browser, router


def run_commands(loop: AppLoop, commands: list) -> None:
    for cmd in commands:
        loop.say(f"\n>> {cmd}")
        loop.busy = True
        loop.jobs.put({"kind": "turn", "text": cmd, "clip": None, "epoch": loop.epoch, "speech_s": 0.0, "wait_ms": 0.0,
                       "hangover": 0.0, "t_trigger": time.perf_counter()})
        while loop.busy:
            time.sleep(0.05)
        time.sleep(0.3)


def waterfall(records: list, args) -> None:
    if not records:
        print("\nNo commands were completed.")
        return
    print("\n" + "=" * 124)
    print(f"{'#':>2} {'tier':<7} {'ok':<5} {'queued':>8} {'silence':>8} {'transcr.':>9} {'browser':>9} {'first sound':>12} {'answer':>8} {'finished':>9}  command")
    for r in records:
        f = lambda ms: f"{ms / 1000:6.2f} s" if ms is not None else "     -  "
        print(f"{r['turn']:>2} {r['tier']:<7} {'yes' if r['ok'] else 'NO':<5} {f(r.get('queued_ms')):>8} {f(r['silence_wait_ms']):>8} {f(r['stt_ms']):>9} "
              f"{f(r['route_ms']):>9} {f(r['first_sound_ms']):>12} {f(r['answer_first_sound_ms']):>8} {f(r['finished_ms']):>9}  {r['command'][:46]}")
    print("=" * 124)
    by = {}
    for r in records:
        by.setdefault(r["tier"], []).append(r)
    for tier, rs in by.items():
        fs = [r["first_sound_ms"] for r in rs if r["first_sound_ms"] is not None]
        fin = [r["finished_ms"] for r in rs]
        print(f"{tier:<7} {len(rs)} commands, {sum(r['ok'] for r in rs)} ok | median first sound "
              f"{statistics.median(fs) / 1000 if fs else float('nan'):.2f} s, median finished {statistics.median(fin) / 1000:.2f} s")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    (HERE / "results").mkdir(exist_ok=True)
    path = HERE / "results" / f"waterfall_{stamp}{'_voice' if not (args.text or args.script) else '_text'}.json"
    path.write_text(json.dumps({"settings": {"hangover_s": args.hangover, "min_speech_s": args.min_speech,
                                             "agent_steps": args.agent_steps, "agent_timeout_s": args.agent_timeout},
                                "commands": records}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"saved {path}")


async def _make_async_client() -> httpx.AsyncClient:
    """Created inside the runner's event loop so it is bound to the loop that will actually await it (planner.plan())."""
    return httpx.AsyncClient(timeout=30)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", action="store_true", help="type commands instead of speaking")
    ap.add_argument("--script", help="file with one command per line; runs them in order")
    ap.add_argument("--no-sound", action="store_true", help="do not play audio (timings are still real)")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--input-device")
    ap.add_argument("--output-device")
    ap.add_argument("--hangover", type=float, default=0.5)
    ap.add_argument("--min-speech", type=float, default=0.25)
    ap.add_argument("--cue", choices=["none", "tick"], default="none")
    ap.add_argument("--idle", type=float, default=0)
    ap.add_argument("--hinglish", action="store_true")
    ap.add_argument("--start-url", default="", help="open this page before listening (so you need not speak an address)")
    ap.add_argument("--agent-steps", type=int, default=8)
    ap.add_argument("--agent-timeout", type=float, default=120.0)
    ap.add_argument("--no-memory", action="store_true",
                    help="Phase 2 off: no conversation-history augmentation, no scratchpad/comparison routing, "
                         "no re-plan on failure (Experiment 9's 'without memory' condition)")
    args = ap.parse_args()
    args.memory = not args.no_memory
    for key in ("input_device", "output_device"):
        v = getattr(args, key)
        if v is not None and v.isdigit():
            setattr(args, key, int(v))
    args.simulate = args.no_sound      # voice_loop's Player simulates the speakers when this is set
    for need in ("DEEPGRAM_API_KEY", "CEREBRAS_API_KEY", "DEEPINFRA_API_KEY") + \
            (() if (args.text or args.script) else ("SARVAM_API_KEY",)):
        if not os.getenv(need):
            raise SystemExit(f"{need} is not set in .env")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    runner = AsyncRunner()
    loop = AppLoop(args, runner)
    print("starting the browser...", flush=True)
    browser, loop.router = make_router(loop, runner, args)
    loop.plan_client = runner.run(_make_async_client())
    if args.start_url:
        res = runner.run(loop.router.run_command(f"go to {args.start_url}"))
        print(f"start page: {args.start_url} ({'ok' if res.ok else 'FAILED: ' + res.detail[:80]})", flush=True)
    try:
        if args.script:
            cmds = [l.strip() for l in Path(args.script).read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.strip().startswith("#")]
            run_commands(loop, cmds)
        elif args.text:
            print("Type a command and press Enter (empty line to quit).", flush=True)
            while True:
                cmd = input("> ").strip()
                if not cmd:
                    break
                run_commands(loop, [cmd])
        else:
            print("Speak a command. Replies are spoken; \"On it.\" means the slow browser agent started. "
                  "Keys: 1 2 3 silence wait, 4 5 6 interruption, q quit.\n", flush=True)
            loop.run(mic_source(args))
    except KeyboardInterrupt:
        pass
    finally:
        waterfall(loop.records, args)
        try:
            if loop.plan_client is not None:
                runner.run(loop.plan_client.aclose(), timeout=5)
        except Exception:
            pass
        try:
            runner.run(browser.kill(), timeout=15)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
