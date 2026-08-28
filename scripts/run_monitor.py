"""The real Monitor job: run scripts/ingest.py's run_ingest() for every
condition in config/tracked_conditions.json.

This is what .github/workflows/monitor.yml actually calls on a schedule.
Tracking a therapeutic area is its own explicit action (see
docs/decisions.md, 2026-08-26, "Discover vs. Monitor") — this file, not an
ad-hoc CLI argument, is the real registry of what's being monitored.

Run manually:
    .venv/bin/python scripts/run_monitor.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ingest import run_ingest  # noqa: E402

CONDITIONS_FILE = ROOT / "config" / "tracked_conditions.json"


def main():
    conditions = json.loads(CONDITIONS_FILE.read_text())
    print(f"Monitor run starting for {len(conditions)} tracked condition(s): {conditions}", flush=True)
    for condition in conditions:
        print(f"\n--- {condition} ---", flush=True)
        run_ingest(condition)
    print("\nMonitor run complete.", flush=True)


if __name__ == "__main__":
    main()
