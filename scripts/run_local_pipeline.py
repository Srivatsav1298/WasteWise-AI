#!/usr/bin/env python3
"""Idempotent local ingestion: raw -> bronze -> silver.

The standard-library DuckDB path replaces the old hand-rolled CSV writer. It is
the default because it needs no cluster, no warehouse credentials and no Spark.

Guarantees
----------
- Re-running the same input produces the same output (deterministic, dedup by
  natural key, bronze snapshots are append-only per run id).
- Invalid rows are quarantined with a reason code; they are never dropped.
- A run manifest is written to ``data/marts/run_metadata.json`` and per-source
  manifests to ``data/silver/_manifests``.

Compatibility
-------------
``data/clean/*.csv`` is still produced for the optional Snowflake loader and for
external tooling. The pre-dbt reason mart is written to ``data/legacy/`` and
never to ``data/marts/``: that folder holds only artefacts the trust engine
approved, and a second, ungated copy of a mart beside the published one is
exactly the ambiguity this project exists to remove.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402

from ingestion import bronze, silver  # noqa: E402
from ingestion.contracts import CONTRACT_VERSION, SOURCES_ORDER  # noqa: E402

CLEAN = ROOT / "data" / "clean"
LEGACY = ROOT / "data" / "legacy"
MART = ROOT / "data" / "marts"


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


def _export_clean_csvs() -> List[Dict]:
    """Publish silver tables as CSV for legacy consumers."""
    CLEAN.mkdir(parents=True, exist_ok=True)
    results = []
    con = duckdb.connect()
    try:
        for source in SOURCES_ORDER:
            stem = Path(source).stem
            path = silver.SILVER / f"{stem}.parquet"
            target = CLEAN / source
            con.execute(
                f"copy (select * from read_parquet('{str(path).replace(chr(39), chr(39) * 2)}')) "
                f"to '{str(target).replace(chr(39), chr(39) * 2)}' (format csv, header true)"
            )
            results.append({"source": source, "clean_path": str(target.relative_to(ROOT))})
    finally:
        con.close()
    return results


def _export_reason_mart() -> Dict:
    """Write the pre-dbt reason mart to data/legacy, never to data/marts."""
    LEGACY.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        rows = con.execute(
            "select reason as reason, round(sum(quantity), 3) as waste_quantity, count(*) as waste_event_count "
            "from read_parquet(?) group by 1 order by 2 desc",
            [str(silver.SILVER / "waste_events.parquet")],
        ).fetchdf()
    finally:
        con.close()
    rows.to_csv(LEGACY / "waste_by_reason.csv", index=False)
    return {"rows": len(rows), "path": str((LEGACY / "waste_by_reason.csv").relative_to(ROOT))}


def main() -> None:
    run_id = _run_id()
    if not (ROOT / "data" / "raw" / "sales.csv").exists():
        from ingestion.generate_synthetic import main as generate

        generate()

    ingested = bronze.ingest_all(SOURCES_ORDER, run_id)
    processed = silver.process_all(SOURCES_ORDER)
    clean = _export_clean_csvs()
    reason_mart = _export_reason_mart()

    metadata = {
        "status": "success",
        "run_id": run_id,
        "contract_version": CONTRACT_VERSION,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": [
            {
                "source": manifest["source"],
                "records": manifest["rows_out"],
                "errors": manifest["rows_rejected"],
                "rows_in": manifest["rows_in"],
                "duplicates_removed": manifest["duplicates_removed"],
            }
            for manifest in processed["sources"]
        ],
        "bronze": {"run_id": ingested["run_id"], "total_rows": ingested["total_rows"]},
        "rows_in": processed["rows_in"],
        "rows_out": processed["rows_out"],
        "rows_rejected": processed["rows_rejected"],
        "duplicates_removed": processed["duplicates_removed"],
        "clean_exports": clean,
        "legacy_marts": {"waste_by_reason": reason_mart},
    }
    MART.mkdir(parents=True, exist_ok=True)
    (MART / "run_metadata.json").write_text(json.dumps(metadata, indent=2))
    print(json.dumps({
        "status": "success",
        "run_id": run_id,
        "rows_in": processed["rows_in"],
        "rows_out": processed["rows_out"],
        "rows_rejected": processed["rows_rejected"],
        "duplicates_removed": processed["duplicates_removed"],
    }, indent=2))


if __name__ == "__main__":
    main()
