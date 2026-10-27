"""Data contracts: single source of truth for source schemas, keys, types and enums.

Every ingested source is described exactly once, here. Contracts are consumed by:

- ``ingestion.silver``      row-level validation, normalization, quarantine
- ``scripts.trust_engine``   declared expectations and severity
- ``docs``                   data dictionary generation

Contract version travels with every run so consumers can detect breaking changes.
"""
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

CONTRACT_VERSION = "2.0.0"

WASTE_REASONS = ["spoilage", "overproduction", "trim", "expired", "damaged", "other"]
UNITS = ["kg", "l", "loaf", "piece", "portion"]  # normalized to lower case by the contract

_STRING = "string"
_NUMBER = "number"
_DATE = "date"


def _c(type_: str, nullable: bool = False, min: Optional[float] = None, max: Optional[float] = None) -> Dict[str, Any]:
    spec: Dict[str, Any] = {"type": type_, "nullable": nullable}
    if min is not None:
        spec["min"] = min
    if max is not None:
        spec["max"] = max
    return spec


SOURCES: Dict[str, Dict[str, Any]] = {
    "sales.csv": {
        "entity": "fct_sales",
        "description": "Point-of-sale unit counts, one row per sale line.",
        "grain": ["sale_id"],
        "natural_key": ["sale_id"],
        "columns": {
            "sale_id": _c(_STRING),
            "location_id": _c(_STRING),
            "sale_date": _c(_DATE),
            "product_id": _c(_STRING),
            "units_sold": _c(_NUMBER, min=0),
        },
        "trim": ["sale_id", "location_id", "product_id"],
        "lowercase": ["location_id", "product_id"],
        "references": {"product_id": "products.csv:product_id", "location_id": "locations.csv:location_id"},
    },
    "inventory_snapshots.csv": {
        "entity": "fct_inventory_snapshot",
        "description": "End-of-day stock on hand, one row per location, date and ingredient.",
        "grain": ["location_id", "snapshot_date", "ingredient_id"],
        "natural_key": ["location_id", "snapshot_date", "ingredient_id"],
        "columns": {
            "snapshot_date": _c(_DATE),
            "location_id": _c(_STRING),
            "ingredient_id": _c(_STRING),
            "quantity_on_hand": _c(_NUMBER, min=0),
        },
        "trim": ["location_id", "ingredient_id"],
        "lowercase": ["location_id", "ingredient_id"],
        "references": {"location_id": "locations.csv:location_id", "ingredient_id": "ingredients.csv:ingredient_id"},
    },
    "waste_events.csv": {
        "entity": "fct_waste_events",
        "description": "Recorded waste, one row per waste event.",
        "grain": ["waste_id"],
        "natural_key": ["waste_id"],
        "columns": {
            "waste_id": _c(_STRING),
            "location_id": _c(_STRING),
            "waste_date": _c(_DATE),
            "ingredient_id": _c(_STRING),
            "quantity": _c(_NUMBER, min=0),
            "reason": _c(_STRING),
        },
        "enums": {"reason": WASTE_REASONS},
        "trim": ["waste_id", "location_id", "ingredient_id", "reason"],
        "lowercase": ["location_id", "ingredient_id", "reason"],
        "references": {"location_id": "locations.csv:location_id", "ingredient_id": "ingredients.csv:ingredient_id"},
    },
    "events.csv": {
        "entity": "fct_demand_events",
        "description": "External demand shocks (conferences, concerts) near a location.",
        "grain": ["event_id"],
        "natural_key": ["event_id"],
        "columns": {
            "event_id": _c(_STRING),
            "event_date": _c(_DATE),
            "event_name": _c(_STRING),
            "event_type": _c(_STRING),
            "venue": _c(_STRING, nullable=True),
            "city": _c(_STRING),
            "expected_attendance": _c(_NUMBER, min=0),
            "attendance_quality": _c(_STRING, nullable=True),
            "source_url": _c(_STRING, nullable=True),
        },
        "trim": ["event_id", "event_name", "event_type", "venue", "city", "attendance_quality", "source_url"],
    },
    "products.csv": {
        "entity": "dim_product",
        "description": "Sold product master with the ingredient each product consumes.",
        "grain": ["product_id"],
        "natural_key": ["product_id"],
        "columns": {
            "product_id": _c(_STRING),
            "product_name": _c(_STRING),
            "category": _c(_STRING),
            "ingredient_id": _c(_STRING),
            "qty_per_unit": _c(_NUMBER, min=0),
            "unit": _c(_STRING),
        },
        "enums": {"unit": UNITS},
        "trim": ["product_id", "product_name", "category", "ingredient_id", "unit"],
        "lowercase": ["product_id", "ingredient_id", "unit"],
        "references": {"ingredient_id": "ingredients.csv:ingredient_id"},
    },
    "ingredients.csv": {
        "entity": "dim_ingredient",
        "description": "Ingredient master with purchase unit and unit cost.",
        "grain": ["ingredient_id"],
        "natural_key": ["ingredient_id"],
        "columns": {
            "ingredient_id": _c(_STRING),
            "ingredient_name": _c(_STRING),
            "category": _c(_STRING),
            "unit": _c(_STRING),
            "pack_size": _c(_NUMBER, min=0),
            "unit_cost": _c(_NUMBER, min=0),
        },
        "enums": {"unit": UNITS},
        "trim": ["ingredient_id", "ingredient_name", "category", "unit"],
        "lowercase": ["ingredient_id", "unit"],
    },
    "locations.csv": {
        "entity": "dim_location",
        "description": "Cafe location master.",
        "grain": ["location_id"],
        "natural_key": ["location_id"],
        "columns": {
            "location_id": _c(_STRING),
            "location_name": _c(_STRING),
            "city": _c(_STRING),
        },
        "trim": ["location_id", "location_name", "city"],
        "lowercase": ["location_id"],
    },
}

SOURCES_ORDER = ["sales.csv", "inventory_snapshots.csv", "waste_events.csv", "events.csv",
                  "products.csv", "ingredients.csv", "locations.csv"]


def get_contract(filename: str) -> Dict[str, Any]:
    """Return the contract specification for a source file."""
    spec = SOURCES.get(filename)
    if spec is None:
        raise KeyError(f"no contract registered for source {filename!r}")
    return {
        "version": CONTRACT_VERSION,
        "source": filename,
        "required_columns": sorted(spec["columns"].keys()),
        "natural_key": spec["natural_key"],
        "grain": spec["grain"],
        "entity": spec["entity"],
        "description": spec["description"],
        "columns": spec["columns"],
        "enums": spec.get("enums", {}),
        "references": spec.get("references", {}),
    }


def _coerce(value: Any, type_: str) -> Any:
    if type_ == _DATE:
        if isinstance(value, datetime):
            return value.date().isoformat()
        return str(value).strip()[:10]
    if type_ == _NUMBER:
        return float(value)
    return str(value).strip()


def normalize_row(filename: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """Apply contract normalization: trim, case-fold, and type coercion."""
    spec = SOURCES[filename]
    out: Dict[str, Any] = {}
    for column, rule in spec["columns"].items():
        raw = row.get(column)
        value = _coerce(raw, rule["type"]) if raw not in (None, "") else None
        if isinstance(value, str):
            if column in spec.get("trim", []):
                value = value.strip()
            if column in spec.get("lowercase", []):
                value = value.lower()
        out[column] = value
    return out


def validate_rows(filename: str, rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate rows against the contract.

    Returns structured errors (row, column, code, message, severity). Blocking
    errors mean the row is quarantined; nothing is ever silently discarded.
    """
    spec = SOURCES.get(filename)
    if spec is None:
        return [{"row": 0, "column": None, "code": "unknown_source", "message": f"no contract for {filename}", "severity": "blocker"}]

    rows = list(rows)
    errors: List[Dict[str, Any]] = []
    if not rows:
        return [{"row": 0, "column": None, "code": "empty_source", "message": f"{filename} contains no rows", "severity": "blocker"}]

    present = set(rows[0].keys())
    missing = set(spec["columns"].keys()) - present
    for column in sorted(missing):
        errors.append({"row": 2, "column": column, "code": "missing_column",
                       "message": f"required column '{column}' is absent", "severity": "blocker"})

    for number, row in enumerate(rows, start=2):
        for column, rule in spec["columns"].items():
            raw = row.get(column)
            if raw in (None, ""):
                if not rule["nullable"]:
                    errors.append({"row": number, "column": column, "code": "null_value",
                                   "message": f"'{column}' is required", "severity": "blocker"})
                continue
            try:
                value = _coerce(raw, rule["type"])
            except (TypeError, ValueError):
                errors.append({"row": number, "column": column, "code": "invalid_type",
                               "message": f"'{column}'={raw!r} is not a valid {rule['type']}", "severity": "blocker"})
                continue
            if rule["type"] == _DATE:
                try:
                    datetime.strptime(value, "%Y-%m-%d")
                except ValueError:
                    errors.append({"row": number, "column": column, "code": "invalid_date",
                                   "message": f"'{column}'={raw!r} is not an ISO date", "severity": "blocker"})
            if rule["type"] == _NUMBER:
                if "min" in rule and value < rule["min"]:
                    errors.append({"row": number, "column": column, "code": "negative_value",
                                   "message": f"'{column}'={value} is below {rule['min']}", "severity": "blocker"})
                if "max" in rule and value > rule["max"]:
                    errors.append({"row": number, "column": column, "code": "value_above_max",
                                   "message": f"'{column}'={value} is above {rule['max']}", "severity": "blocker"})
            allowed = spec.get("enums", {}).get(column)
            if allowed and str(value).strip().lower() not in allowed:
                errors.append({"row": number, "column": column, "code": "enum_violation",
                               "message": f"'{column}'={value!r} not in {allowed}", "severity": "blocker"})
    return errors


def row_is_valid(filename: str, row: Dict[str, Any]) -> bool:
    """Fast per-row check used by the silver layer."""
    spec = SOURCES[filename]
    for column, rule in spec["columns"].items():
        raw = row.get(column)
        if raw in (None, ""):
            if not rule["nullable"]:
                return False
            continue
        try:
            value = _coerce(raw, rule["type"])
        except (TypeError, ValueError):
            return False
        if rule["type"] == _DATE:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                return False
        if rule["type"] == _NUMBER and "min" in rule and value < rule["min"]:
            return False
        allowed = spec.get("enums", {}).get(column)
        if allowed and str(value).strip().lower() not in allowed:
            return False
    return True
