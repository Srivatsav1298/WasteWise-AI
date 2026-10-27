"""Bronze layer: immutable, source-fidelity snapshots of every ingested file.

Design rules
------------
- Bronze never edits data. It records what the source delivered, byte for byte,
  plus lineage metadata (file hash, ingestion time, run id, row number).
- Every run appends a new snapshot. History is the audit trail.
- Values are stored as strings. Type interpretation happens in silver, driven by
  the contract, so a schema drift shows up as a validation error rather than a
  silent coercion.
- Storage is Parquet (ZSTD) written through DuckDB. Parquet is the file format;
  DuckDB is the query engine used to write and read it.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import duckdb

ROOT = Path(__file__).resolve().parents[1]
BRONZE = ROOT / "data" / "bronze"
MANIFESTS = BRONZE / "_manifests"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bronze_path(source: str, run_id: str) -> Path:
    return BRONZE / source / f"{run_id}.parquet"


def ingest_source(
    source: str, raw_path: Path, run_id: str, ingested_at: str | None = None
) -> Dict[str, Any]:
    """Copy one source file into bronze and register a manifest entry."""
    BRONZE.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)

    ingested_at = ingested_at or _now()
    target = bronze_path(source, run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".parquet.tmp")

    con = duckdb.connect()
    try:
        source_path = str(raw_path).replace("'", "''")
        escaped_tmp = str(tmp).replace("'", "''")
        con.execute(
            f"""
            copy (
                select
                    *,
                    '{source}' as _source_file,
                    '{run_id}' as _run_id,
                    '{ingested_at}' as _ingested_at,
                    '{_sha256(raw_path)}' as _source_sha256,
                    row_number() over () as _row_number
                from read_csv('{source_path}', header = true, all_varchar = true)
            ) to '{escaped_tmp}' (format parquet, compression zstd)
            """
        )
        row_count = con.execute(f"select count(*) from read_parquet('{escaped_tmp}')").fetchone()[0]
        columns = [row[0] for row in con.execute(f"describe select * from read_parquet('{escaped_tmp}')").fetchall()]
    finally:
        con.close()

    tmp.replace(target)

    manifest = {
        "source": source,
        "run_id": run_id,
        "ingested_at": ingested_at,
        "source_path": str(raw_path.relative_to(ROOT)) if raw_path.is_relative_to(ROOT) else str(raw_path),
        "source_bytes": raw_path.stat().st_size,
        "source_sha256": _sha256(raw_path),
        "row_count": row_count,
        "columns": columns,
        "bronze_path": str(target.relative_to(ROOT)) if target.is_relative_to(ROOT) else str(target),
        "format": "parquet",
        "compression": "zstd",
    }
    (MANIFESTS / f"{source}.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def ingest_all(sources: List[str], run_id: str) -> Dict[str, Any]:
    """Ingest every registered source from the raw directory.

    One timestamp covers the whole run: every source of a delivery was
    ingested at the same moment. A per-source timestamp would drift by
    seconds depending on where the clock crossed a second boundary, and the
    freshness check would then name a different oldest source from one run to
    the next.
    """
    raw = ROOT / "data" / "raw"
    manifests = []
    ingested_at = _now()
    for source in sources:
        path = raw / source
        if not path.exists():
            raise FileNotFoundError(f"raw source missing: {path}")
        manifests.append(ingest_source(source, path, run_id, ingested_at))
    return {
        "run_id": run_id,
        "ingested_at": ingested_at,
        "sources": manifests,
        "total_rows": sum(m["row_count"] for m in manifests),
    }


def list_snapshots(source: str) -> List[Path]:
    directory = BRONZE / source
    if not directory.exists():
        return []
    return sorted(directory.glob("*.parquet"))
