#!/usr/bin/env python3
"""Publish the warehouse to the files the dashboard reads.

Everything the UI shows comes from here. The dashboard never queries the
warehouse and never computes a metric: it renders the exported tables and the
trust report, so a number on screen is always the number the warehouse
produced and the trust engine approved.

The export is a publish gate: when the trust report says ``blocked`` nothing is
written and the script exits non-zero.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MART = DATA / "marts"
WAREHOUSE = DATA / "warehouse.duckdb"

# table -> export file stem
EXPORTS: Dict[str, str] = {
    "mart_waste_priority": "waste_priority",
    "mart_waste_opportunity": "waste_opportunity",
    "mart_waste_daily": "waste_daily",
    "mart_waste_by_reason": "waste_by_reason",
    "mart_waste_by_ingredient": "waste_by_ingredient",
    "mart_waste_by_category": "waste_by_category",
    "mart_demand_events": "demand_events",
    "mart_purchase_plan": "purchase_plan",
    "mart_metric_registry": "metric_registry",
    "mart_dq_expectations": "dq_expectations",
    "mart_food_loss_summary": "food_loss_summary",
}

# The order rows are published in. DuckDB does not promise an order for a plain
# select, so without this the published files differ between runs of the same
# data. A published artefact has to be reproducible, so every table declares the
# key its rows are sorted by.
ORDER_BY: Dict[str, List[str]] = {
    "mart_waste_priority": ["priority_rank", "waste_date", "location_id", "ingredient_id"],
    "mart_waste_opportunity": ["waste_date", "location_id", "ingredient_id", "waste_reason"],
    "mart_waste_daily": ["waste_date", "location_id"],
    "mart_waste_by_reason": ["waste_reason"],
    "mart_waste_by_ingredient": ["ingredient_id", "location_id"],
    "mart_waste_by_category": ["category"],
    "mart_demand_events": ["event_date", "event_id", "location_id"],
    "mart_purchase_plan": ["location_id", "ingredient_id"],
    "mart_metric_registry": ["metric_key"],
    "mart_dq_expectations": ["check_id"],
    "mart_food_loss_summary": ["is_total", "location_id"],
}

# The dimension tables are published in the same reproducible way.
DIMENSION_ORDER_BY: Dict[str, List[str]] = {
    "dim_location": ["location_id"],
    "dim_ingredient": ["ingredient_id"],
    "dim_product": ["product_id"],
    "dim_waste_reason": ["waste_reason"],
    "dim_date": ["date_key"],
}

# Floating point sums depend on the order the rows are added up in, so the same
# data can add up to 17.67 or 17.669999999999998. Published numbers are rounded
# to the precision they are meaningful at, so the file is stable and the number
# on screen is the number a reader would quote.
FLOAT_PRECISION: int = 6


def _records(con: duckdb.DuckDBPyConnection, sql: str) -> List[Dict[str, Any]]:
    frame = con.execute(sql).fetchdf()
    return frame.to_dict("records")


def _round_floats(value: Any) -> Any:
    """Round every float to a stable precision, deep inside the structure."""
    if isinstance(value, dict):
        return {key: _round_floats(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round_floats(item) for item in value]
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return value
        rounded = round(value, FLOAT_PRECISION)
        # Keep whole numbers whole so the published file does not say 12.0
        # where the warehouse says 12.
        return int(rounded) if rounded == int(rounded) else rounded
    if hasattr(value, "tolist"):
        return _round_floats(value.tolist())
    if hasattr(value, "item"):
        return _round_floats(value.item())
    return value


def _sanitize(value: Any) -> Any:
    """Replace values JSON cannot represent (NaN, Infinity) with null.

    ``NaN`` is not valid JSON, and the dashboard parses these files with
    ``JSON.parse``. A missing value must arrive as ``null``.
    """
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if hasattr(value, "tolist"):
        return _sanitize(value.tolist())
    if hasattr(value, "item"):
        return _sanitize(value.item())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _write_json(path: Path, payload: Any) -> int:
    clean = _sanitize(_round_floats(payload))
    path.write_text(json.dumps(clean, indent=2, allow_nan=False))
    return len(clean) if isinstance(clean, list) else 1


# Finder names of the artefacts that contain measured numbers. When the gate is
# closed these are removed, so a reader cannot see last run's numbers stamped
# with this run's status. Definitions and diagnostics (the registry, the
# expectations, the trust report, the lineage) are kept: they are what explains
# the block and they do not go stale the way a number does.
MEASUREMENT_STEMS: List[str] = [
    "waste_priority",
    "waste_opportunity",
    "waste_daily",
    "waste_by_reason",
    "waste_by_ingredient",
    "waste_by_category",
    "demand_events",
    "purchase_plan",
    "food_loss_summary",
    "overview",
]


def _purge_stale_measurements() -> List[str]:
    """Remove previously published numbers so a blocked run shows no numbers."""
    removed: List[str] = []
    for stem in MEASUREMENT_STEMS:
        path = MART / f"{stem}.json"
        if path.exists():
            path.unlink()
            removed.append(f"{stem}.json")
    return removed


def _displayable_states(report: Dict[str, Any]) -> Dict[str, bool]:
    """Which metrics the trust engine allows to be shown as a number."""
    states: Dict[str, bool] = {}
    for metric in report.get("metrics", []):
        states[metric["metric_key"]] = bool(metric.get("displayable"))
    return states


# Registry metrics that appear as a column in a published table. When the trust
# engine refuses the metric, the columns it feeds are published as null rather
# than as the number, so the dashboard cannot show a figure the gate did not
# approve. The key is the registry metric that gates the column.
METRIC_COLUMNS: Dict[str, List[str]] = {
    # The order cost is derived from the order quantity, so the same metric
    # gates both. A cost with no quantity behind it is a number with no meaning.
    "recommended_order_qty": ["recommended_order_qty", "recommended_order_cost"],
}

# Which export file each gated column belongs to.
COLUMN_TABLES: Dict[str, str] = {
    "recommended_order_qty": "purchase_plan",
    "recommended_order_cost": "purchase_plan",
}


def _apply_column_gate(stem: str, rows: List[Dict[str, Any]], displayable: Dict[str, bool]) -> None:
    for metric_key, columns in METRIC_COLUMNS.items():
        if COLUMN_TABLES.get(columns[0]) != stem:
            continue
        if displayable.get(metric_key, False):
            continue
        for row in rows:
            for column in columns:
                if column in row:
                    row[column] = None


def main() -> int:
    MART.mkdir(parents=True, exist_ok=True)
    status_path = MART / "publish_status.json"
    if not status_path.exists():
        # Nothing declares the data publishable, so nothing may be served.
        removed = _purge_stale_measurements()
        print(
            "no publish status found, run the trust engine first"
            + (f" (removed stale: {', '.join(removed)})" if removed else ""),
            file=sys.stderr,
        )
        return 1
    status = json.loads(status_path.read_text())
    if status.get("status") != "published":
        removed = _purge_stale_measurements()
        print(
            f"publish blocked: {status.get('blockers')}"
            + (f" (removed stale: {', '.join(removed)})" if removed else ""),
            file=sys.stderr,
        )
        return 1

    report_path = MART / "trust_report.json"
    if not report_path.exists():
        print("no trust report found, run the trust engine first", file=sys.stderr)
        return 1
    report = json.loads(report_path.read_text())
    displayable = _displayable_states(report)

    con = duckdb.connect(str(WAREHOUSE))
    written: List[str] = []
    try:
        for table, stem in EXPORTS.items():
            order = ", ".join(ORDER_BY[table])
            rows = _records(con, f"select * from main.{table} order by {order}")
            _apply_column_gate(stem, rows, displayable)
            _write_json(MART / f"{stem}.json", rows)
            written.append(f"{stem}.json")

        # Overview aggregates are published, not computed in the browser. They are
        # read from mart_food_loss_summary so the published number, the published
        # lineage and the published definition come from the same model.
        estate = _records(
            con,
            "select * from main.mart_food_loss_summary where is_total = 1",
        )[0]

        def allowed(metric_key: str) -> bool:
            return displayable.get(metric_key, False)

        overview = {
            "waste_cost_at_risk": [
                {
                    "value": estate["avoidable_cost"] if allowed("waste_cost_at_risk") else None,
                    "rows_measured": estate["avoidable_events"] if allowed("waste_cost_at_risk") else None,
                }
            ],
            "waste_quantity": [
                {
                    "value": estate["waste_quantity"] if allowed("waste_quantity") else None,
                    "rows_measured": estate["waste_events"] if allowed("waste_quantity") else None,
                }
            ],
            "avoidable_share": [
                {"value": estate["avoidable_cost_share"] if allowed("avoidable_cost_share") else None}
            ],
            "waste_rate_per_demand": [
                {
                    "value": estate["waste_rate_per_demand"] if allowed("waste_rate_per_demand") else None,
                    "rows_with_denominator": (
                        estate["events_with_demand_denominator"]
                        if allowed("waste_rate_per_demand")
                        else None
                    ),
                    "denominator": (
                        estate["ingredient_demand_qty"] if allowed("waste_rate_per_demand") else None
                    ),
                }
            ],
            "locations": _records(
                con,
                "select location_id, location_name, city, waste_cost, waste_quantity, "
                "waste_events as events, waste_rate_per_demand "
                "from main.mart_food_loss_summary where is_total = 0 "
                "order by waste_cost desc, location_id",
            ),
            "top_ingredients": _records(
                con,
                "select ingredient_id, ingredient_name, ingredient_category, "
                "round(sum(estimated_cost), 2) as waste_cost, round(sum(waste_quantity), 3) as waste_quantity "
                "from main.mart_waste_priority group by 1,2,3 "
                "order by waste_cost desc, ingredient_id limit 10",
            ),
            "daily_trend": _records(
                con,
                "select waste_date, location_id, waste_quantity, estimated_cost, "
                "rolling_7d_avg_waste_qty from main.mart_waste_daily "
                "order by waste_date, location_id",
            ),
        }
        _write_json(MART / "overview.json", overview)
        written.append("overview.json")

        # Dimension and reference tables the UI needs for filters and labels.
        for table, stem in (
            ("dim_location", "dim_location"),
            ("dim_ingredient", "dim_ingredient"),
            ("dim_product", "dim_product"),
            ("dim_waste_reason", "dim_waste_reason"),
            ("dim_date", "dim_date"),
        ):
            order = ", ".join(DIMENSION_ORDER_BY[table])
            rows = _records(con, f"select * from main.{table} order by {order}")
            _write_json(MART / f"{stem}.json", rows)
            written.append(f"{stem}.json")
    finally:
        con.close()

    print(json.dumps({"status": "published", "files": sorted(written)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
