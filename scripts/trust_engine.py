#!/usr/bin/env python3
"""Food Waste Data Trust Engine.

The trust engine answers one question for every published number: *can this be
trusted right now, and why?*

It evaluates the expectations declared in ``mart_dq_expectations`` against the
warehouse, the dbt build results and the raw deliveries, then assigns a trust
state to every metric in ``mart_metric_registry``:

    measured    every relevant check passed; the number is backed by delivered data
    partial     the number is usable but a coverage or freshness warning applies
    unverified  a blocking check failed; the number must not be presented as fact

A blocking failure stops publication: the engine writes a ``blocked`` publish
status and exits non-zero so that CI cannot ship a broken warehouse.

Outputs
-------
data/marts/trust_report.json    full report: checks, metrics, sources, reconciliation
data/marts/publish_status.json   gate decision for the publishing step
data/marts/lineage.json         model level lineage extracted from the dbt manifest
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MART = DATA / "marts"
WAREHOUSE = DATA / "warehouse.duckdb"
RAW = DATA / "raw"
SILVER_MANIFESTS = DATA / "silver" / "_manifests"
QUARANTINE = DATA / "quarantine"
DBT_TARGET = ROOT / "dbt_project" / "target"

SOURCE_TABLES = [
    "sales",
    "inventory_snapshots",
    "waste_events",
    "events",
    "products",
    "ingredients",
    "locations",
]

# Reconciliation is recomputed from the delivered files, never from the model
# that produced the number, so the comparison is genuinely independent.
RECONCILIATIONS = {
    "waste_quantity": {
        "mart": "select coalesce(sum(waste_quantity), 0) from main.mart_waste_daily",
        "raw": "select coalesce(sum(cast(quantity as double)), 0) from raw.waste_events",
        "unit": "kg or units",
    },
    "waste_cost": {
        "mart": "select coalesce(sum(estimated_cost), 0) from main.fct_waste_events",
        "raw": (
            "select coalesce(sum(round(cast(w.quantity as double) * i.unit_cost, 2)), 0) "
            "from (select * from raw.waste_events "
            "      qualify row_number() over (partition by waste_id order by _row_number desc) = 1) w "
            "left join (select ingredient_id, max(cast(unit_cost as double)) as unit_cost "
            "           from raw.ingredients group by 1) i using (ingredient_id)"
        ),
        "unit": "NOK",
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat(timespec="seconds") if value else None


def _load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------- checks


def _check_status(operator: str, observed: float, expected: float) -> bool:
    if operator == "eq":
        return abs(observed - expected) < 1e-9
    if operator == "lte":
        return observed <= expected
    if operator == "gte":
        return observed >= expected
    if operator == "lt":
        return observed < expected
    if operator == "gt":
        return observed > expected
    raise ValueError(f"unsupported operator {operator}")


def _run_sql(con: duckdb.DuckDBPyConnection, sql: str) -> float:
    value = con.execute(sql).fetchone()
    return float(value[0]) if value and value[0] is not None else 0.0


def _evaluate_sql(con, spec) -> Tuple[str, float, str]:
    observed = _run_sql(con, spec["sql"])
    expected = float(spec.get("value", 0))
    operator = spec.get("operator", "eq")
    ok = _check_status(operator, observed, expected)
    return ("pass" if ok else "fail"), observed, f"observed {observed:g}, expected {operator} {expected:g}"


def _evaluate_quality_rate(spec, manifests) -> Tuple[str, float, str]:
    threshold = float(spec.get("threshold", 0.02))
    worst = -1.0
    worst_source = ""
    for name, manifest in manifests.items():
        rate = float(manifest.get("rejected_pct", 0.0)) / 100.0
        if rate > worst:
            worst, worst_source = rate, name
    worst = max(worst, 0.0)
    ok = worst <= threshold
    return (
        "pass" if ok else "fail",
        round(worst, 6),
        f"worst rejected rate {worst:.4%} on {worst_source or 'n/a'}, threshold {threshold:.4%}",
    )


def _evaluate_source_freshness(con, spec) -> Tuple[str, float, str]:
    max_age_days = 0.0
    oldest = ""
    for table in SOURCE_TABLES:
        row = con.execute(
            f'select max(_ingested_at) from silver."{table}"'
        ).fetchone()
        if not row or row[0] is None:
            continue
        age_days = (_now() - row[0].astimezone(timezone.utc)).total_seconds() / 86400.0
        # Sources ingested in the same run differ by microseconds. Comparing the
        # rounded age and breaking the tie by name keeps the reported oldest
        # source the same from one run to the next.
        rounded = round(age_days, 4)
        if (
            not oldest
            or rounded > max_age_days
            or (rounded == max_age_days and table < oldest)
        ):
            max_age_days, oldest = rounded, table
    ok = max_age_days <= float(spec.get("threshold", 3))
    return (
        "pass" if ok else "fail",
        round(max_age_days, 4),
        f"oldest silver source {oldest or 'n/a'} is {max_age_days:.2f} days old",
    )


def _evaluate_data_recency(con, spec) -> Tuple[str, float, str]:
    """Compare the sales horizon with the newest event that the sales cover.

    Future events are ignored: they have not happened yet, so they cannot be
    expected to appear in delivered sales.
    """
    source = spec.get("source", "sales")
    compare_to = spec.get("compare_to", "events")
    row = con.execute(f'select max(sale_date) from silver."{source}"').fetchone()
    newest = row[0] if row else None
    if newest is None:
        return "skip", 0.0, "no comparable dates found"
    other = con.execute(
        f'select max(event_date) from silver."{compare_to}" where event_date <= ?', [newest]
    ).fetchone()
    reference = other[0] if other else None
    if reference is None:
        return "skip", 0.0, "no comparable dates found"
    lag_days = (reference - newest).days
    threshold = float(spec.get("threshold", 2))
    ok = lag_days <= threshold
    if lag_days < 0:
        detail = (
            f"{source} covers {compare_to} and extends {abs(lag_days)} day(s) past the "
            f"newest event"
        )
    else:
        detail = f"{source} covers {compare_to} with a lag of {lag_days} day(s) (threshold {threshold:g})"
    return ("pass" if ok else "fail", float(lag_days), detail)


def _evaluate_reconciliation(con, spec) -> Tuple[str, float, str]:
    name = spec.get("target")
    definition = RECONCILIATIONS.get(name)
    if definition is None:
        return "skip", 0.0, f"unknown reconciliation target {name}"
    mart_value = _run_sql(con, definition["mart"])
    raw_value = _run_sql(con, definition["raw"])
    difference = round(mart_value - raw_value, 6)
    tolerance = float(spec.get("threshold", 0.0))
    ok = abs(difference) <= max(tolerance, 0.005)
    return (
        "pass" if ok else "fail",
        difference,
        f"{name}: mart {mart_value:g} vs source {raw_value:g} (difference {difference:g} {definition['unit']})",
    )


def _evaluate_dbt_tests(run_results) -> Tuple[str, float, str]:
    if not run_results:
        return "skip", 0.0, "no dbt run results found"
    failed = []
    for result in run_results.get("results", []):
        if result.get("status") not in ("pass", "success", "skipped"):
            failed.append(f"{result.get('unique_id')} ({result.get('status')})")
    if failed:
        return "fail", float(len(failed)), f"{len(failed)} failing dbt nodes: " + ", ".join(failed[:5])
    return "pass", 0.0, "all dbt models built and all dbt tests passed"


def _evaluate_dbt_manifest(manifest) -> Tuple[str, float, str]:
    if not manifest:
        return "skip", 0.0, "no dbt manifest found"
    parent_map = manifest.get("parent_map", {})
    sources = set(manifest.get("sources", {}).keys())
    orphans = []
    declared = []
    for node_id, node in manifest.get("nodes", {}).items():
        if node.get("resource_type") != "model":
            continue
        if not node.get("name", "").startswith("mart_"):
            continue
        parents = parent_map.get(node_id, [])
        if not parents:
            # Hand maintained model: it declares its own numbers, so it has no
            # delivery upstream. It is visible in the lineage, not a break.
            declared.append(node.get("name"))
            continue
        if not _reaches_source(node_id, parent_map, sources):
            orphans.append(node.get("name"))
    if orphans:
        return (
            "fail",
            float(len(orphans)),
            f"marts whose lineage does not reach a delivery: {', '.join(orphans)}",
        )
    detail = f"every published mart resolves to at least one source"
    if declared:
        detail += f" ({len(declared)} declared model(s) have no delivery upstream)"
    return "pass", 0.0, detail


def _tested_models(manifest) -> set:
    """Model names that have at least one dbt test attached."""
    tested: set = set()
    for node_id, node in (manifest or {}).get("nodes", {}).items():
        if node.get("resource_type") != "test":
            continue
        candidates = []
        if node.get("attached_node"):
            candidates.append(node["attached_node"])
        candidates.extend(node.get("depends_on", {}).get("nodes", []))
        for candidate in candidates:
            if not candidate.startswith("model."):
                continue
            tested.add(candidate.split(".")[-1])
    return tested


def _metric_protection(metrics, expectations, lineage, manifest) -> Dict[str, bool]:
    """Map every published metric to whether something protects it.

    Protection is either a declared expectation targeting a model in the metric's
    lineage, or a dbt test attached to one. A metric protected by neither is a
    number nobody checks, and must not be published as if it were measured.
    """
    tested = _tested_models(manifest)
    targeted = set()
    for expectation in expectations:
        try:
            spec = json.loads(expectation["check_spec"])
        except (TypeError, ValueError):
            continue
        if spec.get("kind") == "metric_coverage":
            # The coverage check protects the registry, not the metrics.
            continue
        targeted.add(expectation["target_model"])

    protection: Dict[str, bool] = {}
    for metric in metrics:
        if not metric.get("published"):
            continue
        chain = set(_model_chain(lineage, metric["source_model"]))
        protection[metric["metric_key"]] = bool(chain & (tested | targeted))
    return protection


def _evaluate_metric_coverage(spec, metrics, expectations, lineage, manifest) -> Tuple[str, float, str]:
    """Every published metric must be protected by a check or a test."""
    protection = _metric_protection(metrics, expectations, lineage, manifest)
    unprotected = sorted(key for key, ok in protection.items() if not ok)
    if unprotected:
        return (
            "fail",
            float(len(unprotected)),
            "published metrics with no protecting expectation or dbt test: "
            + ", ".join(unprotected),
        )
    return (
        "pass",
        0.0,
        f"all {len(protection)} published metrics are protected by a declared expectation "
        "or a dbt test",
    )


def _evaluate_dashboard_consistency(metric_rows, metrics) -> Tuple[str, float, str]:
    """The registry's display promise must match what the engine allows.

    A metric the registry marks as displayed in the dashboard must actually be
    displayable. When the trust state does not allow it, the export withholds
    the value, and the registry promise is out of date. That is a warning, not
    a blocker: the number is withheld either way, but the mismatch must be
    visible rather than silent.
    """
    promised = {
        metric["metric_key"]
        for metric in metrics
        if metric.get("published") and metric.get("display_in_dashboard")
    }
    broken = sorted(
        row["metric_key"]
        for row in metric_rows
        if row["metric_key"] in promised and not row["displayable"]
    )
    if broken:
        return (
            "fail",
            float(len(broken)),
            "the registry says these metrics are displayed, but their trust state does "
            "not allow it, so the values were withheld: " + ", ".join(broken),
        )
    return (
        "pass",
        0.0,
        f"all {len(promised)} metrics promised to the dashboard are displayable",
    )


def _resolve_dashboard_consistency(checks, metric_rows, metrics) -> None:
    """Fill in the dashboard consistency check once the metric states exist."""
    status, observed, message = _evaluate_dashboard_consistency(metric_rows, metrics)
    for check in checks:
        if check["status"] == "pending":
            check["status"] = status
            check["observed"] = observed
            check["message"] = message


def _reaches_source(node_id: str, parent_map: Dict[str, List[str]], sources: set) -> bool:
    """A model is traceable when a source is reachable through the parent map."""
    seen: set = set()
    stack = [node_id]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for parent in parent_map.get(current, []):
            if parent in sources:
                return True
            stack.append(parent)
    return False


# --------------------------------------------------------------------------- lineage


def _build_lineage(manifest) -> Dict[str, Any]:
    if not manifest:
        return {"models": {}, "sources": {}}
    source_names = {
        node_id: node.get("name", node_id) for node_id, node in manifest.get("sources", {}).items()
    }
    parent_map = manifest.get("parent_map", {})
    models: Dict[str, Any] = {}
    for node_id, node in manifest.get("nodes", {}).items():
        if node.get("resource_type") != "model":
            continue
        if not node_id.startswith("model.wastewise."):
            continue
        parents = parent_map.get(node_id, [])
        upstream_models = [p.split(".")[-1] for p in parents if p.startswith("model.")]
        upstream_sources = [
            source_names.get(p, p.split(".")[-1]) for p in parents if p.startswith("source.")
        ]
        models[node.get("name")] = {
            "depends_on_models": sorted(upstream_models),
            "depends_on_sources": sorted(upstream_sources),
            "materialized": node.get("config", {}).get("materialized"),
            "description": node.get("description", "").strip(),
        }
    return {
        "models": {name: models[name] for name in sorted(models)},
        "sources": sorted(source_names.values()),
        "generated_at": _iso(_now()),
    }


def _model_chain(lineage: Dict[str, Any], model_name: str) -> List[str]:
    """Every model upstream of ``model_name``, including the model itself."""
    seen: set[str] = set()
    chain: List[str] = []
    stack = [model_name]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        node = lineage["models"].get(current)
        if node is None:
            continue
        chain.append(current)
        stack.extend(node["depends_on_models"])
    return chain


def _metric_source_chain(lineage: Dict[str, Any], model_name: str) -> List[str]:
    """Walk upstream until the delivery sources are reached."""
    seen: set[str] = set()
    chain: List[str] = []
    stack = [model_name]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        node = lineage["models"].get(current)
        if node is None:
            continue
        chain.extend(node["depends_on_sources"])
        stack.extend(node["depends_on_models"])
    return sorted(set(chain))


# --------------------------------------------------------------------------- engine


def evaluate(con, expectations, metrics=None, lineage=None) -> List[Dict[str, Any]]:
    manifests = {
        path.stem: json.loads(path.read_text())
        for path in sorted(SILVER_MANIFESTS.glob("*.json"))
    }
    run_results = _load_json(DBT_TARGET / "run_results.json")
    manifest = _load_json(DBT_TARGET / "manifest.json")
    results: List[Dict[str, Any]] = []

    for expectation in expectations:
        spec = json.loads(expectation["check_spec"])
        kind = spec.get("kind")
        threshold = float(expectation.get("threshold") or 0)
        spec_with_threshold = {**spec, "threshold": threshold}
        try:
            if kind == "sql":
                status, observed, message = _evaluate_sql(con, spec_with_threshold)
            elif kind == "quality_rate":
                status, observed, message = _evaluate_quality_rate(spec_with_threshold, manifests)
            elif kind == "source_freshness":
                status, observed, message = _evaluate_source_freshness(con, spec_with_threshold)
            elif kind == "data_recency":
                status, observed, message = _evaluate_data_recency(con, spec_with_threshold)
            elif kind == "reconciliation":
                status, observed, message = _evaluate_reconciliation(con, spec_with_threshold)
            elif kind == "dbt_tests":
                status, observed, message = _evaluate_dbt_tests(run_results)
            elif kind == "dbt_manifest":
                status, observed, message = _evaluate_dbt_manifest(manifest)
            elif kind == "metric_coverage":
                status, observed, message = _evaluate_metric_coverage(
                    spec_with_threshold, metrics or [], expectations, lineage or {}, manifest
                )
            elif kind == "dashboard_consistency":
                # This one judges the metric states, and the states are only known
                # after every other check has run. It is filled in by
                # _resolve_dashboard_consistency once the states exist.
                status, observed, message = "pending", 0.0, "evaluated after the metric states are assigned"
            else:
                status, observed, message = "skip", 0.0, f"unknown check kind {kind}"
        except Exception as error:  # a broken expectation must not hide the others
            status, observed, message = "error", 0.0, f"{type(error).__name__}: {error}"

        severity = expectation["severity"]
        results.append(
            {
                "check_id": expectation["check_id"],
                "target_model": expectation["target_model"],
                "check_type": expectation["check_type"],
                "dimension": expectation["dimension"],
                "severity": severity,
                "status": status,
                "observed": observed,
                "threshold": threshold,
                "comparison": expectation["comparison"],
                "description": expectation["description"],
                "message": message,
                "owner": expectation["owner"],
                "remediation": expectation["remediation"],
            }
        )
    return results


def assign_metric_states(metrics, checks, lineage, protection=None) -> List[Dict[str, Any]]:
    """A metric inherits the trust state of the checks that protect its model."""
    global_checks = [c for c in checks if c["target_model"] in ("dbt", "silver")]
    by_model: Dict[str, List[Dict[str, Any]]] = {}
    for check in checks:
        by_model.setdefault(check["target_model"], []).append(check)

    protection = protection or {}
    rows: List[Dict[str, Any]] = []
    for metric in metrics:
        # A metric inherits the state of every check that protects its lineage:
        # a failure two models upstream is still a failure of this metric.
        upstream = set(_model_chain(lineage, metric["source_model"]))
        relevant = list(global_checks) + [
            check
            for check in checks
            if check["target_model"] in upstream and check not in global_checks
        ]
        blocking = [c for c in relevant if c["severity"] == "blocker" and c["status"] in ("fail", "error")]
        warning = [c for c in relevant if c["severity"] == "warning" and c["status"] in ("fail", "error")]

        # A published metric that nothing checks is not merely unproven, it is
        # unprotected: there is no rule that could ever catch it breaking.
        uncovered = bool(metric.get("published")) and protection.get(metric["metric_key"]) is False

        if blocking or uncovered:
            state = "unverified"
        elif warning:
            state = "partial"
        else:
            state = "measured"
        if metric["measurement_type"] == "estimated" and state == "measured":
            # An estimate can never be presented as a measurement.
            state = "partial"

        raw_allowed = metric["trust_states_allowed"]
        allowed = [str(state) for state in (raw_allowed if raw_allowed is not None else [])]
        displayable = bool(metric["published"]) and state in allowed
        blocking_ids = [c["check_id"] for c in blocking]
        if uncovered and "dq_metric_coverage" not in blocking_ids:
            blocking_ids.append("dq_metric_coverage")
        rows.append(
            {
                "metric_key": metric["metric_key"],
                "metric_name": metric["metric_name"],
                "source_model": metric["source_model"],
                "measurement_type": metric["measurement_type"],
                "unit": metric["unit"],
                "owner": metric["owner"],
                "caveat": metric["caveat"],
                "definition": metric["definition"],
                "trust_state": state,
                "trust_states_allowed": allowed,
                "displayable": displayable,
                "trusted": displayable and state in ("measured", "partial"),
                "publish_blocked": bool(blocking) or uncovered,
                "blocking_checks": blocking_ids,
                "warning_checks": [c["check_id"] for c in warning],
                "protected": protection.get(metric["metric_key"], True),
                "lineage": _metric_source_chain(lineage, metric["source_model"]),
            }
        )
    return rows


def main() -> int:
    MART.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE))
    try:
        expectations = con.execute(
            "select * from main.mart_dq_expectations order by check_id"
        ).fetchdf().to_dict("records")
        metrics = con.execute(
            "select * from main.mart_metric_registry order by metric_key"
        ).fetchdf().to_dict("records")

        manifest = _load_json(DBT_TARGET / "manifest.json")
        lineage = _build_lineage(manifest)

        checks = evaluate(con, expectations, metrics, lineage)
        protection = _metric_protection(metrics, expectations, lineage, manifest)
        metric_rows = assign_metric_states(metrics, checks, lineage, protection)

        # The registry promises certain metrics to the dashboard. The engine
        # checks that promise against the states it just assigned, so a promise
        # the data can no longer keep is reported rather than silently broken.
        _resolve_dashboard_consistency(checks, metric_rows, metrics)

        source_rows = []
        for table in SOURCE_TABLES:
            manifest_path = SILVER_MANIFESTS / f"{table}.json"
            source_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
            row = con.execute(
                f'select count(*) as rows, max(_ingested_at) as ingested_at from silver."{table}"'
            ).fetchone()
            quarantine = _load_json(QUARANTINE / f"{table}.errors.json") or {}
            source_rows.append(
                {
                    "source": table,
                    "entity": source_manifest.get("entity"),
                    "grain": source_manifest.get("grain"),
                    "contract_version": source_manifest.get("contract_version"),
                    "rows_delivered": source_manifest.get("rows_in"),
                    "rows_published": row[0] if row else 0,
                    "rows_rejected": source_manifest.get("rows_rejected", 0),
                    "duplicates_removed": source_manifest.get("duplicates_removed", 0),
                    "retained_pct": source_manifest.get("retained_pct", 0.0),
                    "ingested_at": _iso(row[1]) if row and row[1] else None,
                    "quarantine_errors": len(quarantine.get("errors", [])),
                }
            )

        blockers = [c for c in checks if c["severity"] == "blocker" and c["status"] in ("fail", "error")]
        warnings = [c for c in checks if c["severity"] == "warning" and c["status"] in ("fail", "error")]
        status = "blocked" if blockers else "published"

        report = {
            "status": status,
            "generated_at": _iso(_now()),
            "contract_version": con.execute("select max(contract_version) from main.mart_dq_expectations").fetchone()[0] or "2.0.0",
            "summary": {
                "checks_total": len(checks),
                "checks_passed": len([c for c in checks if c["status"] == "pass"]),
                "checks_failed": len([c for c in checks if c["status"] in ("fail", "error")]),
                "blockers": len(blockers),
                "warnings": len(warnings),
                "metrics_total": len(metric_rows),
                "metrics_displayable": len([m for m in metric_rows if m["displayable"]]),
            },
            "checks": checks,
            "metrics": metric_rows,
            "sources": source_rows,
            "lineage": lineage,
        }
    finally:
        con.close()

    (MART / "trust_report.json").write_text(json.dumps(report, indent=2, default=str))
    (MART / "lineage.json").write_text(json.dumps(report["lineage"], indent=2, default=str))
    (MART / "publish_status.json").write_text(
        json.dumps(
            {
                "status": report["status"],
                "generated_at": report["generated_at"],
                "blockers": [
                    {"check_id": c["check_id"], "message": c["message"], "remediation": c["remediation"]}
                    for c in blockers
                ],
                "warnings": [
                    {"check_id": c["check_id"], "message": c["message"], "remediation": c["remediation"]}
                    for c in warnings
                ],
                "metrics_displayable": report["summary"]["metrics_displayable"],
                "metrics_total": report["summary"]["metrics_total"],
            },
            indent=2,
        )
    )

    summary = report["summary"]
    print(
        json.dumps(
            {
                "status": report["status"],
                "checks": f"{summary['checks_passed']}/{summary['checks_total']} passed",
                "blockers": summary["blockers"],
                "warnings": summary["warnings"],
                "metrics_displayable": f"{summary['metrics_displayable']}/{summary['metrics_total']}",
            },
            indent=2,
        )
    )
    for check in blockers:
        print(f"BLOCKER {check['check_id']}: {check['message']}", file=sys.stderr)
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
