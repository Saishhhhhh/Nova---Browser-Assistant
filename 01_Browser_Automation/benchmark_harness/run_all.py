"""
Master Benchmark Orchestrator: runs all 4 browser automation contenders sequentially
and generates a consolidated report.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmark_harness.server.app import start_server
from benchmark_harness.reporter import generate_report


def run_command(cmd: list[str], cwd: Path, desc: str) -> bool:
    print(f"\n{'='*70}\n[MASTER RUNNER] Executing: {desc}\nCommand: {' '.join(cmd)}\n{'='*70}")
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), check=True)
        elapsed = time.perf_counter() - t0
        print(f"[MASTER RUNNER] Completed: {desc} in {elapsed:.1f}s (code {proc.returncode})")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[MASTER RUNNER] FAILED: {desc} with exit code {e.returncode}")
        return False
    except Exception as e:
        print(f"[MASTER RUNNER] ERROR running {desc}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Master Browser Automation Benchmark Orchestrator")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser window")
    parser.add_argument("--smoke", action="store_true", help="Run 1 iteration quick sanity check")
    parser.add_argument("--iterations", type=int, default=5, help="Number of benchmark iterations")
    parser.add_argument("--suite", choices=["local", "live", "all"], default="local", help="Benchmark suite to run")
    parser.add_argument("--port", type=int, default=8765, help="Local test server port")
    args = parser.parse_args()

    iters_flag = ["--smoke"] if args.smoke else ["--iterations", str(args.iterations)]
    headed_flag = ["--headed"] if args.headed else []

    # 1. Start test server
    print(f"[MASTER RUNNER] Starting local test server on port {args.port}...")
    server, _ = start_server(args.port)

    try:
        contenders_dir = PROJECT_ROOT / "contenders"

        # List of benchmark tasks
        tasks = []

        if args.suite in ("local", "all"):
            tasks.extend([
                ("Raw CDP (Local)", [sys.executable, "bench_local.py"] + iters_flag + headed_flag, contenders_dir / "01_raw_cdp"),
                ("nodriver (Local)", [sys.executable, "bench_local.py"] + iters_flag + headed_flag, contenders_dir / "02_nodriver"),
                ("Playwright (Local)", [sys.executable, "bench_local.py"] + iters_flag + headed_flag, contenders_dir / "03_playwright"),
                ("Puppeteer (Local)", ["node", "bench_local.js"] + iters_flag + headed_flag, contenders_dir / "04_puppeteer"),
            ])

        if args.suite in ("live", "all"):
            tasks.extend([
                ("Raw CDP (Live)", [sys.executable, "bench_live.py"] + headed_flag, contenders_dir / "01_raw_cdp"),
                ("nodriver (Live)", [sys.executable, "bench_live.py"] + headed_flag, contenders_dir / "02_nodriver"),
                ("Playwright (Live)", [sys.executable, "bench_live.py"] + headed_flag, contenders_dir / "03_playwright"),
                ("Puppeteer (Live)", ["node", "bench_live.js"] + headed_flag, contenders_dir / "04_puppeteer"),
            ])

        success_count = 0
        for desc, cmd, cwd in tasks:
            ok = run_command(cmd, cwd, desc)
            if ok:
                success_count += 1

        print(f"\n[MASTER RUNNER] Finished {success_count}/{len(tasks)} tasks successfully.")

        # 2. Generate consolidated report
        generate_report()

    finally:
        print("[MASTER RUNNER] Shutting down test server...")
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
