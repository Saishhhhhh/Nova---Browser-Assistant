"""Nova: a voice-driven browser assistant that acts on your real Brave browser.

  python run_nova.py                          # voice: say "Nova, <command>" - Brave opens with your real profile
  python run_nova.py --text                   # type commands instead of speaking (no microphone, no overlay)
  python run_nova.py --script commands.txt    # run a list of commands automatically, then print the waterfall

What happens to each voice command (the "waterfall"): you stop speaking -> silence wait (VAD) -> transcript
(ElevenLabs) -> wake-word gate (did you say "Nova"?) -> router (rules, then one short model call, then the
full browser agent) -> a spoken reply. If the router has to start the slow browser agent, "On it." is spoken
at once so you are not left in silence.

A request that joins several actions ("Nova, go to Amazon, search for MSI monitors, and tell me the
cheapest one") is split into steps by the planner instead of being handed whole to the agent. Say "Nova,
stop" at any point to cancel.

REAL API CALLS and a real, visible Brave window: DeepInfra for the fast-path's model step and the planner,
Cerebras for the agent, ElevenLabs and Deepgram for speech. Voice mode needs HEADPHONES.

This is the finished app assembled from the `experiments/` folder's nine rounds of building and live-testing;
see WRITEUP.md for that whole journey, and experiments/09_Memory_and_Replanning/README.md for the detailed,
turn-by-turn account of the bugs found live and fixed.
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

import httpx

from . import config, openwakeword_wake
from .browser import launch as launch_brave
from .dom_fastpath import parse_command, make_picker_from_env
from .identity import GREETING
from .memory import COMPARE_QUESTION, ConversationMemory, compare_from_scratchpad, needs_memory
from .overlay import Overlay, OverlayState, pick_devices
from .planner import looks_multi_step, parse_step, plan, replan_after_failure
from .router import QUESTION, RouterResult, CommandRouter, clean_command, is_correction
from .voice import Loop, mic_source, save_clip, transcribe
from .wakeword import strip_wake_word

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent   # repo root - results/ lives here, not inside the nova/ package itself
ACK = "On it."
STILL = "Still working on it."
SPOKEN_LIMIT = 220   # characters; past this, speech takes longer than it's worth. The console/log/memory
                     # still get the FULL reply - only what's actually spoken out loud is shortened.
HEARTBEAT_FIRST_S, HEARTBEAT_EVERY_S = 12.0, 15.0
CANCEL = re.compile(r"^(?:stop|cancel|never mind|nevermind|forget it|abort|halt|enough)(?![a-z])", re.I)


def _speakable(text: str) -> str:
    if len(text) <= SPOKEN_LIMIT:
        return text
    cut = text[:SPOKEN_LIMIT].rsplit(" ", 1)[0]
    return f"{cut}... there's more in the log."


class AsyncRunner:
    """browser-use is asynchronous; the voice side is threads. This runs one asyncio loop in its own thread."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def run(self, coro, timeout=None):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)


class AppLoop(Loop):
    """The voice loop, with the router in place and a wake-word gate in front of it."""

    def __init__(self, args, runner, overlay_state: OverlayState = None):
        super().__init__(args, on_state=self._on_state if overlay_state is not None else None)
        self.runner = runner
        self.overlay_state = overlay_state
        self.router = None        # set once the browser is up
        self.records = []
        self._cur = None
        self.slow_running = False   # a command is going through the slow path (model step or agent)
        self.cancelled = False
        self.pending = None         # (verb, time) after "Click what?": the next words complete the command
        self.plan_client = None     # httpx.AsyncClient for planner.plan(), set once the browser/router are up
        self.plan_active = False    # a multi-step plan is currently running (set for its whole duration, not
        self.plan_cancelled = False  # just the current step), so "stop" cancels the whole plan, not one step
        self.memory = ConversationMemory()
        self._clip_no = 0
        self.clip_dir = ROOT / "results" / f"clips_{datetime.datetime.now():%Y%m%d_%H%M%S}"

    def _on_state(self, state: str) -> None:
        self.overlay_state.set(state)

    def _save_turn_clip(self, job: dict, text: str, ms: float) -> None:
        clip = job.get("clip")
        if clip is None or not getattr(self.args, "save_clips", True):
            return
        self._clip_no += 1
        try:
            save_clip(clip, self._clip_no, self.clip_dir)
            (self.clip_dir / f"turn_{self._clip_no:03d}.json").write_text(
                json.dumps({"text": text, "stt_ms": round(ms), "engine": self.args.stt}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _wake_decision(self, text: str, job: dict) -> tuple:
        """Was this utterance addressed to Nova, and what's left to route once the name is cleaned out?

        Two independent signals, combined with OR: the acoustic detector (nova/openwakeword_wake.py,
        job["wake_addressed"] - did it hear "Nova" in the raw audio?) and the text-based check
        (nova/wakeword.py's strip_wake_word() - does the transcript contain "Nova"?). Found live: a
        quieter/rushed "Hey Nova" was missed acoustically but still correctly transcribed by STT, and
        got rejected anyway because only the acoustic signal was trusted. Either one catching it is now
        enough - this can only accept MORE utterances than acoustic-only did, never fewer, so it doesn't
        reopen the old text-only failure modes (anywhere-in-sentence matching is unchanged below).
        Without openWakeWord installed, the text check is the only signal there is, same as before."""
        text_addressed, remainder = strip_wake_word(text)
        addressed = text_addressed or (openwakeword_wake.available() and bool(job.get("wake_addressed")))
        return addressed, (remainder if remainder.strip() else text)

    # --- turn-taking rules specific to the app
    def barge_applies(self) -> bool:
        return self.speaking or self.player.pending_s() > 0

    def interrupt(self, why: str, heard_ms: float) -> None:
        if self.slow_running:
            self.player.stop()
            return
        super().interrupt(why, heard_ms)

    def submit(self, job: dict) -> None:
        if self.slow_running and job["kind"] == "turn" and job.get("text") is None:
            threading.Thread(target=self._while_busy, args=(job,), daemon=True).start()
        else:
            self.jobs.put(job)

    def _while_busy(self, job: dict) -> None:
        """You spoke while the browser is working: "Nova, stop" cancels outright; a correction also cancels
        the in-flight step and queues the corrected command; anything else just queues."""
        try:
            text, ms = transcribe(self.http, job["clip"], self.args.hinglish, engine=self.args.stt)
        except Exception as e:
            self.say(f"  !! {type(e).__name__}: {str(e)[:150]}")
            return
        self._save_turn_clip(job, text, ms)
        addressed, remainder = self._wake_decision(text, job)
        if not addressed:
            self.say(f"  (heard \"{text.strip()}\" - not addressed to Nova, ignored)")
            return
        heard = clean_command(remainder)
        if CANCEL.match(heard):
            self.say(f"  (heard \"{text.strip()}\" -> stop)")
            self.cancel_agent()
            return
        if not remainder.strip():
            return
        if is_correction(remainder):
            self.say(f"  (heard a correction: \"{remainder.strip()}\"; cancelling the current step)")
            self.cancel_agent()
        job["text"], job["stt_ms"] = remainder, ms
        self.say(f"  (heard \"{remainder.strip()}\" while working; it will run next)")
        self.jobs.put(job)

    def _drain_queue(self) -> int:
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

        def beat():
            waited = 0.0
            while not cur.get("done") and not self.cancelled:
                time.sleep(0.5)
                waited += 0.5
                if waited >= HEARTBEAT_FIRST_S and (waited - HEARTBEAT_FIRST_S) % HEARTBEAT_EVERY_S < 0.5 \
                        and not self.speaking and self.player.pending_s() == 0:
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
        if job.get("text") is not None:
            text, stt_ms = job["text"], float(job.get("stt_ms", 0.0))
        else:
            text, stt_ms = transcribe(self.http, job["clip"], self.args.hinglish, engine=self.args.stt)
            self._save_turn_clip(job, text, stt_ms)
        if job["epoch"] != self.epoch:
            self.say(f"  (you spoke again; dropped \"{text}\")")
            return
        if not text.strip():
            self.say("  (nothing recognised)")
            return
        # The wake-word gate only applies to live voice mode. Text/script mode (dev/test use, including this
        # app's own test suite) has no mic and no overlay - requiring "Nova, ..." there would just be friction
        # with no benefit, since there's no ambient room conversation to filter out.
        wake_gate_active = (getattr(self.args, "wake_word", True)
                             and not getattr(self.args, "text", False) and not getattr(self.args, "script", None))
        if wake_gate_active and not job.get("_wake_checked"):
            addressed, remainder = self._wake_decision(text, job)
            if not addressed:
                self.say(f"  (heard \"{text.strip()}\" - not addressed to Nova, ignored)")
                return
            text = remainder
            if not text.strip():
                self.say("  (heard my name, nothing after it)")
                return
        if self.pending and time.time() - self.pending[1] < 10:
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
        queued_ms = max(0.0, (time.perf_counter() - t_end) * 1000 - job["wait_ms"] - stt_ms)
        cur = {"epoch": job["epoch"], "t_speech_end": t_end, "ack_ms": None}
        self._cur = cur
        to_run = text
        if self.args.memory and len(text.split()) > 2 and needs_memory(text):
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
            cur["ack_thread"].join()
        if self.cancelled:
            self.cancelled = False
            self.say("  (stopped; no answer spoken)")
            return
        if res.tier == "chat":
            if res.reply:
                self._speak(_speakable(res.reply), job["epoch"], {})
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
        self._speak(_speakable(res.reply), job["epoch"], meta)
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
        queued = f"queued {queued_ms / 1000:.2f} | " if queued_ms > 100 else ""
        self.say(f"          waterfall: {queued}silence {rec['silence_wait_ms'] / 1000:.2f} | transcript {rec['stt_ms'] / 1000:.2f} | "
                 f"browser step {rec['route_ms'] / 1000:.2f} [{rec['tier']}{', ' + str(rec['agent_steps']) + ' steps' if rec['agent_steps'] else ''}] | "
                 f"voice {meta.get('tts_first_audio_ms', 0) / 1000:.2f}   ->  first sound {((rec['first_sound_ms'] or 0) / 1000):.2f} s{ack}, "
                 f"answer {(rec['answer_first_sound_ms'] or 0) / 1000:.2f} s, finished {rec['finished_ms'] / 1000:.2f} s")

    def _handle_plan(self, text: str, stt_ms: float, job: dict) -> None:
        t_end = job["t_trigger"] - job["wait_ms"] / 1000
        queued_ms = max(0.0, (time.perf_counter() - t_end) * 1000 - job["wait_ms"] - stt_ms)
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
        steps = list(steps)
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
                    self._speak(_speakable(f"I got to step {i} of {len(steps)}, but then: {res.reply}"), job["epoch"], {})
                    return
                self.say(f"  (step {i}/{len(steps)} ok [{res.tier}]: \"{step}\" -> {res.reply[:150]!r})")
                self._speak(_speakable(res.reply), job["epoch"], {})
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


async def _make_async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30)


def make_router(loop: AppLoop, runner: AsyncRunner, args):
    """Live voice mode: Brave, your real profile. Text/script mode: plain headless Chromium, so testing
    never requires closing your browser first."""
    from browser_use import Browser

    if args.text or args.script:
        browser = Browser(headless=True, no_viewport=True, keep_alive=True)
        runner.run(browser.start())
    else:
        browser = runner.run(launch_brave())
    picker = make_picker_from_env()
    router = CommandRouter(
        browser, picker=picker, agent_llm=config.get_browser_use_llm("cerebras"),
        extraction_llm=config.get_browser_use_llm(config.EXTRACTION_PROVIDER, config.EXTRACTION_MODEL)
        if config.EXTRACTION_PROVIDER else None,
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
    (ROOT / "results").mkdir(exist_ok=True)
    path = ROOT / "results" / f"waterfall_{stamp}{'_voice' if not (args.text or args.script) else '_text'}.json"
    path.write_text(json.dumps({"settings": {"hangover_s": args.hangover, "min_speech_s": args.min_speech,
                                             "agent_steps": args.agent_steps, "agent_timeout_s": args.agent_timeout},
                                "commands": records}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"saved {path}")


def _run_backend(loop: AppLoop, runner: AsyncRunner, args, overlay_state: OverlayState):
    """Everything that used to be in main(): opens the browser, greets you, then either runs a script, a
    typed-command loop, or the live mic loop. Runs in a background thread when there's an overlay (voice
    mode), so Tkinter can own the main thread; called directly otherwise (text/script mode)."""
    print("starting the browser...", flush=True)
    try:
        browser, loop.router = make_router(loop, runner, args)
    except Exception as e:
        print(f"could not start: {e}", flush=True)
        if overlay_state:
            overlay_state.set("error", str(e)[:60])
        return
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
            print("Type a command and press Enter (empty line to quit). No wake word needed in text mode.", flush=True)
            while True:
                cmd = input("> ").strip()
                if not cmd:
                    break
                run_commands(loop, [cmd])
        else:
            print(f"Say \"Nova\" before a command - for example \"Nova, open GitHub.\" Say \"Nova, stop\" to cancel.\n", flush=True)
            threading.Thread(target=lambda: loop._speak(GREETING, loop.epoch, {}), daemon=True).start()
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
        if overlay_state:
            os._exit(0)   # the overlay window is the only thing left on the main thread; close the process with it


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", action="store_true", help="type commands instead of speaking (no overlay, no wake word)")
    ap.add_argument("--script", help="file with one command per line; runs them in order (no overlay, no wake word)")
    ap.add_argument("--no-sound", action="store_true", help="do not play audio (timings are still real)")
    ap.add_argument("--no-wake-word", action="store_true", help="act on every command, skip the \"Nova\" gate (voice mode only)")
    ap.add_argument("--hangover", type=float, default=0.5)
    ap.add_argument("--min-speech", type=float, default=0.25)
    ap.add_argument("--cue", choices=["none", "tick"], default="none")
    ap.add_argument("--idle", type=float, default=0)
    ap.add_argument("--hinglish", action="store_true")
    ap.add_argument("--start-url", default="", help="open this page before listening")
    ap.add_argument("--agent-steps", type=int, default=8)
    ap.add_argument("--agent-timeout", type=float, default=120.0)
    ap.add_argument("--no-memory", action="store_true", help="no conversation-history/scratchpad/re-plan-on-failure")
    ap.add_argument("--stt", choices=["elevenlabs", "sarvam"], default="elevenlabs",
                    help="elevenlabs (default): most accurate. sarvam: faster, better for Hinglish.")
    ap.add_argument("--no-save-clips", action="store_true", help="don't save each turn's audio to results/clips_*/")
    args = ap.parse_args()
    args.memory = not args.no_memory
    args.save_clips = not args.no_save_clips
    args.wake_word = not args.no_wake_word
    args.simulate = args.no_sound

    device_cfg = config.load_device_config()
    args.input_device = device_cfg.get("input_device")
    args.output_device = device_cfg.get("output_device")

    for need in ("DEEPGRAM_API_KEY", "CEREBRAS_API_KEY", "DEEPINFRA_API_KEY") + \
            (() if (args.text or args.script) else
             (("SARVAM_API_KEY",) if args.stt == "sarvam" else ("ELEVENLABS_API_KEY",))):
        if not os.getenv(need):
            raise SystemExit(f"{need} is not set in .env")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    runner = AsyncRunner()

    if args.text or args.script:
        # Developer/test mode: no overlay, no Brave, no wake-word gate - straight to the console.
        loop = AppLoop(args, runner)
        _run_backend(loop, runner, args, overlay_state=None)
        return 0

    # Live voice mode: Tkinter must own the main thread, so everything else runs in a background thread.
    overlay_state = OverlayState()
    loop = AppLoop(args, runner, overlay_state=overlay_state)

    def on_pick_devices():
        current = {"input_device": args.input_device, "output_device": args.output_device}
        chosen = pick_devices(overlay.root, current)
        config.save_device_config(chosen)
        overlay_state.set("listening", "device change takes effect next run")

    overlay = Overlay(overlay_state, assistant_name=config.ASSISTANT_NAME, on_pick_devices=on_pick_devices)
    overlay.root.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))
    threading.Thread(target=_run_backend, args=(loop, runner, args, overlay_state), daemon=True).start()
    overlay.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
