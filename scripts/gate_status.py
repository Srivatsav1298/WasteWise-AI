#!/usr/bin/env python3
"""Report the state of the publication gate.

This is the one place that answers "may these numbers be shown?", and it
answers it from the published artefacts rather than from the database, so the
scheduler, the CI job and the dashboard all read the same verdict.

Exit codes
    0  the gate is open: the numbers are published and every published metric
       is protected
    2  the gate is closed: a blocking expectation failed and the numbers were
       withdrawn
    1  the gate state is missing or unreadable, or a published metric has no
       protection
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
MART = ROOT / "data" / "marts"


def _load(name: str) -> Any:
    path = MART / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def read_gate() -> Dict[str, Any]:
    """Read the gate state from the published artefacts."""
    status = _load("publish_status.json") or {}
    report = _load("trust_report.json") or {}
    summary = report.get("summary") or {}
    metrics = report.get("metrics") or []
    unprotected = sorted(
        metric["metric_key"]
        for metric in metrics
        if metric.get("published") and not metric.get("protected", True)
    )
    return {
        "status": status.get("status"),
        "generated_at": status.get("generated_at"),
        "blockers": status.get("blockers") or [],
        "checks_passed": summary.get("checks_passed"),
        "checks_total": summary.get("checks_total"),
        "warnings": summary.get("warnings"),
        "metrics_displayable": summary.get("metrics_displayable"),
        "metrics_total": summary.get("metrics_total"),
        "unprotected_metrics": unprotected,
    }


def _print_human(gate: Dict[str, Any]) -> None:
    if gate["status"] == "published":
        print(
            f"publish gate open: {gate['checks_passed']} of {gate['checks_total']} "
            "expectations passed"
        )
        print(
            f"metrics displayable: {gate['metrics_displayable']} of {gate['metrics_total']}"
        )
        return
    print(f"publish gate closed: {len(gate['blockers'])} blocking expectation(s) failed")
    for blocker in gate["blockers"]:
        print(f"  {blocker.get('check_id')}: {blocker.get('message')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Report the state of the publication gate.")
    parser.add_argument("--json", action="store_true", help="print the gate state as JSON")
    parser.add_argument(
        "--tolerate-blocked",
        action="store_true",
        help="exit 0 when the gate is closed (the withdrawal was the designed outcome)",
    )
    parser.add_argument(
        "--state",
        action="store_true",
        help="print only the state of the gate: published, blocked or missing",
    )
    args = parser.parse_args()

    gate = read_gate()
    if args.state:
        state = gate["status"]
        if state is None:
            print("missing")
            return 1
        print(state)
        return 0 if state == "published" else 1

    if gate["status"] is None:
        print(
            "publish_status.json is missing: the trust engine has not published a "
            "verdict yet"
        )
        return 1

    if args.json:
        print(json.dumps(gate, indent=2))
    else:
        _print_human(gate)

    if gate["unprotected_metrics"]:
        print(
            "published metrics without protection: "
            + ", ".join(gate["unprotected_metrics"])
        )
        return 1

    if gate["status"] == "published":
        return 0
    return 0 if args.tolerate_blocked else 2


if __name__ == "__main__":
    raise SystemExit(main())
