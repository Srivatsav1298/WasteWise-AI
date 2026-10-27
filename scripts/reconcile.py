#!/usr/bin/env python3
"""Delivery reconciliation: what came in, what was published, what was rejected.

The numbers here come from the silver manifests and the quarantine files, so
this report is independent of the warehouse. The trust engine compares the two
views against each other.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MART = DATA / "marts"
MANIFESTS = DATA / "silver" / "_manifests"
QUARANTINE = DATA / "quarantine"


def _load(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def main() -> int:
    MART.mkdir(parents=True, exist_ok=True)
    sources: Dict[str, Any] = {}
    totals = {"rows_in": 0, "rows_out": 0, "rows_rejected": 0, "duplicates_removed": 0}

    for manifest_path in sorted(MANIFESTS.glob("*.json")):
        manifest = _load(manifest_path) or {}
        name = manifest.get("source", manifest_path.stem)
        quarantine = _load(QUARANTINE / f"{manifest_path.stem}.errors.json") or {}
        errors = quarantine.get("errors", [])
        entry = {
            "entity": manifest.get("entity"),
            "grain": manifest.get("grain"),
            "contract_version": manifest.get("contract_version"),
            "bronze_snapshot": manifest.get("bronze_snapshot"),
            "silver_path": manifest.get("silver_path"),
            "rows_delivered": manifest.get("rows_in", 0),
            "rows_published": manifest.get("rows_out", 0),
            "rows_rejected": manifest.get("rows_rejected", 0),
            "duplicates_removed": manifest.get("duplicates_removed", 0),
            "retained_pct": manifest.get("retained_pct", 0.0),
            "rejected_pct": manifest.get("rejected_pct", 0.0),
            "quarantine_errors": [
                {"row": item.get("row"), "errors": item.get("errors", [])} for item in errors
            ],
            "ingested_at": manifest.get("generated_at"),
        }
        sources[name] = entry
        # The totals use the same vocabulary as the run metadata
        # (rows_in / rows_out); the per-source ledger uses the delivery
        # vocabulary (rows_delivered / rows_published).
        for total_key, entry_key in (
            ("rows_in", "rows_delivered"),
            ("rows_out", "rows_published"),
            ("rows_rejected", "rows_rejected"),
            ("duplicates_removed", "duplicates_removed"),
        ):
            totals[total_key] += int(entry.get(entry_key, 0) or 0)

    report = {
        "generated_at": manifest.get("generated_at") if sources else None,
        "totals": totals,
        "sources": sources,
    }
    (MART / "reconciliation.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({"status": "reconciled", "totals": totals}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
