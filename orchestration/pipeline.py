"""Batch entry point for the full pipeline.

A scheduler can call this command on a schedule without changing any job:

    python -m orchestration.pipeline

Order matters. Nothing downstream may run before the layer it depends on is
fresh, and publication is gated on the trust engine.

    1. deliver      synthetic or real files land in data/raw
    2. bronze       immutable snapshot of every delivery
    3. silver       contract validation, typing, dedup, quarantine
    4. dbt build    staging, facts, dimensions, marts and their tests
    5. trust        expectations evaluated, trust states assigned
    6. publish      marts and the trust report exported for consumers

Step 5 fails the run when a blocking expectation breaks. Step 6 still runs in
that case: it withdraws the previously published numbers and refuses to write
new ones, so a blocked run never leaves stale figures on disk.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
DBT_PROJECT = ROOT / "dbt_project"


def _run(label: str, command: List[str], cwd: Path | None = None) -> None:
    print(f"[pipeline] {label}: {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=str(cwd) if cwd else None)
    if result.returncode != 0:
        raise SystemExit(f"[pipeline] {label} failed with exit code {result.returncode}")


def steps(include_delivery: bool = True) -> List[Tuple[str, List[str], Path | None]]:
    plan: List[Tuple[str, List[str], Path | None]] = []
    if include_delivery:
        plan.append(("deliver", [sys.executable, str(ROOT / "ingestion" / "generate_synthetic.py")], None))
    plan.append(("bronze+silver", [sys.executable, str(ROOT / "scripts" / "run_local_pipeline.py")], None))
    plan.append(("reconcile", [sys.executable, str(ROOT / "scripts" / "reconcile.py")], None))
    plan.append(("dbt build", ["dbt", "build", "--profiles-dir", "."], DBT_PROJECT))
    plan.append(("trust engine", [sys.executable, str(ROOT / "scripts" / "trust_engine.py")], None))
    plan.append(("publish", [sys.executable, str(ROOT / "scripts" / "export_marts.py")], None))
    return plan


def run(include_delivery: bool = True) -> None:
    plan = steps(include_delivery)
    failure: SystemExit | None = None
    for label, command, cwd in plan:
        try:
            _run(label, command, cwd)
        except SystemExit as error:
            failure = error
            # A refused build still has to withdraw the previously published
            # numbers. The trust engine closes the gate and exits non-zero, so
            # the publish step has to run anyway; it removes the stale figures
            # and refuses to write new ones.
            if label == "trust engine":
                publish = next((step for step in plan if step[0] == "publish"), None)
                if publish is not None:
                    try:
                        _run(*publish)
                    except SystemExit:
                        pass
            break
    if failure is not None:
        raise failure
    print(json.dumps({"status": "success", "message": "pipeline completed"}), flush=True)


if __name__ == "__main__":
    run(include_delivery="--no-delivery" not in sys.argv)
