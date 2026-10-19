"""Telemetry recording and benchmark reporting system."""
import os
import json
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional, Any, Dict, List
from tabulate import tabulate


@dataclass
class BenchmarkRunResult:
    candidate: str
    provider: str
    model: str
    task_id: str
    task_name: str
    success: bool
    total_duration_sec: float
    time_to_first_action_sec: Optional[float] = None
    step_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    extracted_data: Any = None
    error_message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class TelemetryLogger:
    def __init__(self, results_dir: Optional[str] = None):
        if results_dir is None:
            results_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results"
            )
        self.results_dir = results_dir
        os.makedirs(self.results_dir, exist_ok=True)

    def record_run(self, result: BenchmarkRunResult) -> str:
        """Saves individual run to JSON and updates the consolidated markdown summary."""
        filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{result.candidate}_{result.task_id}.json"
        filepath = os.path.join(self.results_dir, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(asdict(result), f, indent=2)

        self._regenerate_summary_markdown()
        return filepath

    def _regenerate_summary_markdown(self):
        """Scans all JSON files in results_dir and creates summary_table.md."""
        runs: List[Dict[str, Any]] = []
        for file in os.listdir(self.results_dir):
            if file.endswith(".json"):
                try:
                    with open(os.path.join(self.results_dir, file), "r", encoding="utf-8") as f:
                        runs.append(json.load(f))
                except Exception:
                    pass

        if not runs:
            return

        # Sort runs by timestamp
        runs.sort(key=lambda x: x.get("timestamp", ""))

        headers = [
            "Timestamp",
            "Candidate",
            "Model",
            "Task",
            "Success",
            "Duration (s)",
            "TTFA (s)",
            "Steps",
            "Tokens (Total)",
            "Error",
        ]
        rows = []
        for r in runs:
            rows.append([
                r.get("timestamp", "")[:19].replace("T", " "),
                r.get("candidate", ""),
                r.get("model", "")[:20],
                r.get("task_id", ""),
                " PASS" if r.get("success") else " FAIL",
                f"{r.get('total_duration_sec', 0):.2f}",
                f"{r.get('time_to_first_action_sec', 0):.2f}" if r.get("time_to_first_action_sec") is not None else "N/A",
                r.get("step_count", 0),
                f"{r.get('total_tokens', 0):,}",
                (r.get("error_message") or "")[:30],
            ])

        summary_path = os.path.join(self.results_dir, "SUMMARY.md")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("# Browser Automation Benchmark Summary\n\n")
            f.write(f"Total Runs Recorded: {len(runs)}\n\n")
            f.write(tabulate(rows, headers=headers, tablefmt="github"))
            f.write("\n")
