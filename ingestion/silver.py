"""Silver layer: contracted, typed, deduplicated and quarantined data.

Responsibilities
----------------
- Read the newest bronze snapshot for each source (deliveries are full
  snapshots, so the newest delivery defines current state).
- Validate every row against :mod:`ingestion.contracts`.
- Quarantine invalid rows with an actionable reason code. Nothing is dropped
  silently: rejected rows are written to ``data/silver/rejects`` and to
  ``data/quarantine/<source>.errors.json``.
- Normalize types and casing.
- Deduplicate on the natural key, keeping the last delivered row.
- Write typed Parquet plus a manifest that records the full data-quality
  ledger for the source.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import duckdb
import pandas as pd

from . import bronze
from .contracts import CONTRACT_VERSION, SOURCES, SOURCES_ORDER, normalize_row, validate_rows

ROOT = Path(__file__).resolve().parents[1]
SILVER = ROOT / "data" / "silver"
REJECTS = SILVER / "rejects"
QUARANTINE = ROOT / "data" / "quarantine"
RAW = ROOT / "data" / "raw"
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"

TYPE_SQL = {"string": "varchar", "number": "double", "date": "date"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _latest_snapshot(source: str) -> Path | None:
    snapshots = bronze.list_snapshots(source)
    return snapshots[-1] if snapshots else None


def _read_snapshot(path: Path) -> List[Dict[str, Any]]:
    con = duckdb.connect()
    try:
        frame = con.execute(
            f"select * from read_parquet('{str(path).replace(chr(39), chr(39) * 2)}')"
        ).fetchdf()
    finally:
        con.close()
    return frame.to_dict("records")


LINEAGE_COLUMNS = ["_source_file", "_ingested_at", "_source_sha256", "_run_id", "_row_number"]


def _write_parquet(rows: List[Dict[str, Any]], spec: Dict[str, Any], target: Path, lineage: Dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".parquet.tmp")
    columns = spec["columns"]
    frame = pd.DataFrame(rows, columns=list(columns.keys())) if rows else pd.DataFrame(columns=list(columns.keys()))
    for column in LINEAGE_COLUMNS:
        frame[column] = lineage.get(column)
    con = duckdb.connect()
    try:
        con.register("_silver_frame", frame)
        select = ", ".join(
            f'cast("{column}" as {TYPE_SQL[rule["type"]]}) as "{column}"' for column, rule in columns.items()
        )
        select += (
            ", cast(\"_ingested_at\" as timestamp) as \"_ingested_at\""
            ", \"_source_file\" as \"_source_file\""
            ", \"_source_sha256\" as \"_source_sha256\""
            ", \"_run_id\" as \"_run_id\""
            ", \"_row_number\" as \"_row_number\""
        )
        con.execute(
            f"copy (select {select} from _silver_frame) to '{str(tmp).replace(chr(39), chr(39) * 2)}' "
            f"(format parquet, compression zstd)"
        )
    finally:
        con.close()
    tmp.replace(target)


def _write_rejects(rows: List[Dict[str, Any]], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["_source_file", "_row_number"])
    con = duckdb.connect()
    try:
        con.register("_reject_frame", frame)
        con.execute(
            f"copy (select * from _reject_frame) to '{str(target).replace(chr(39), chr(39) * 2)}' "
            f"(format parquet, compression zstd)"
        )
    finally:
        con.close()


def _publish_to_warehouse(source: str, silver_path: Path) -> None:
    """Materialize raw and silver tables inside the DuckDB warehouse.

    The warehouse is the analytical store that dbt reads from. Keeping the
    tables inside it (instead of scanning loose Parquet files with relative
    paths) means every consumer, human or machine, sees the same data
    regardless of the directory it runs from.
    """
    stem = Path(source).stem
    csv_path = (RAW / source).resolve()
    con = duckdb.connect(str(WAREHOUSE))
    try:
        con.execute("create schema if not exists raw")
        con.execute("create schema if not exists silver")
        if csv_path.exists():
            con.execute(
                f"create or replace table raw.\"{stem}\" as "
                f"select *, row_number() over () as _row_number "
                f"from read_csv('{_sql_str(csv_path)}', header=true, all_varchar=true)"
            )
        con.execute(
            f"create or replace table silver.\"{stem}\" as "
            f"select * from read_parquet('{_sql_str(silver_path.resolve())}')"
        )
    finally:
        con.close()


def _sql_str(path: Path) -> str:
    return str(path).replace("'", "''")


def process_source(source: str) -> Dict[str, Any]:
    """Validate, normalize, dedupe and publish one source to silver."""
    spec = SOURCES[source]
    snapshot = _latest_snapshot(source)
    if snapshot is None:
        raise FileNotFoundError(f"no bronze snapshot available for {source}")

    raw_rows = _read_snapshot(snapshot)
    snapshot_rows = raw_rows
    errors = validate_rows(source, raw_rows)
    error_by_row: Dict[int, List[Dict[str, Any]]] = {}
    for error in errors:
        error_by_row.setdefault(error["row"], []).append(error)

    # Row numbers in contracts are 1-based file lines (header = line 1).
    valid: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    rejected_index: List[int] = []
    for index, row in enumerate(raw_rows):
        line = index + 2
        row_errors = error_by_row.get(line, [])
        if row_errors:
            rejected.append({**row, "_rejected_reason": row_errors[0]["code"], "_rejected_detail": row_errors[0]["message"]})
            rejected_index.append(line)
            continue
        valid.append(normalize_row(source, row))

    key = spec["natural_key"]
    deduped: Dict[Tuple, Dict[str, Any]] = {}
    for row in valid:
        deduped[tuple(row[column] for column in key)] = row
    unique_rows = list(deduped.values())
    duplicates_removed = len(valid) - len(unique_rows)

    SILVER.mkdir(parents=True, exist_ok=True)
    REJECTS.mkdir(parents=True, exist_ok=True)
    QUARANTINE.mkdir(parents=True, exist_ok=True)

    target = SILVER / f"{Path(source).stem}.parquet"
    _write_parquet(unique_rows, spec, target, {
        "_source_file": snapshot_rows[0].get("_source_file") if snapshot_rows else source,
        "_ingested_at": snapshot_rows[0].get("_ingested_at") if snapshot_rows else "",
        "_source_sha256": snapshot_rows[0].get("_source_sha256") if snapshot_rows else "",
        "_run_id": snapshot_rows[0].get("_run_id") if snapshot_rows else "",
        "_row_number": None,
    })
    reject_target = REJECTS / f"{Path(source).stem}.parquet"
    _write_rejects(rejected, reject_target)

    # Human-readable quarantine manifest (kept for tooling and for the UI).
    quarantine_doc = {
        "source": source,
        "run_id": snapshot.stem,
        "generated_at": _now(),
        "rejected_rows": len(rejected),
        "errors": [
            {"row": line, "errors": error_by_row.get(line, [])} for line in rejected_index
        ],
    }
    (QUARANTINE / f"{Path(source).stem}.errors.json").write_text(json.dumps(quarantine_doc, indent=2))

    manifest = {
        "source": source,
        "entity": spec["entity"],
        "grain": spec["grain"],
        "natural_key": key,
        "contract_version": CONTRACT_VERSION,
        "bronze_snapshot": str(snapshot.relative_to(ROOT)) if snapshot.is_relative_to(ROOT) else str(snapshot),
        "silver_path": str(target.relative_to(ROOT)) if target.is_relative_to(ROOT) else str(target),
        "rows_in": len(raw_rows),
        "rows_valid": len(valid),
        "rows_rejected": len(rejected),
        "duplicates_removed": duplicates_removed,
        "rows_out": len(unique_rows),
        "retained_pct": round(len(unique_rows) / len(raw_rows) * 100, 2) if raw_rows else 0.0,
        "rejected_pct": round(len(rejected) / len(raw_rows) * 100, 2) if raw_rows else 0.0,
        "columns": {name: rule["type"] for name, rule in spec["columns"].items()},
        "generated_at": _now(),
    }
    (SILVER / "_manifests").mkdir(parents=True, exist_ok=True)
    (SILVER / "_manifests" / f"{Path(source).stem}.json").write_text(json.dumps(manifest, indent=2))
    _publish_to_warehouse(source, target)
    return manifest


def process_all(sources: List[str] | None = None) -> Dict[str, Any]:
    manifests = [process_source(source) for source in (sources or SOURCES_ORDER)]
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": _now(),
        "sources": manifests,
        "rows_in": sum(m["rows_in"] for m in manifests),
        "rows_out": sum(m["rows_out"] for m in manifests),
        "rows_rejected": sum(m["rows_rejected"] for m in manifests),
        "duplicates_removed": sum(m["duplicates_removed"] for m in manifests),
    }
