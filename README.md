# WasteWiseAI

Food waste intelligence for a three-cafe group, built around one idea: **a number
without a trust state is not a number you can act on.**

Every figure the dashboard shows is published by the warehouse, and every figure
carries a trust state (`measured`, `partial`, `unverified`) produced by the Data
Trust Engine. Where the data cannot support a claim, the platform refuses the
claim instead of publishing a plausible one.

## What it does

| View | Question it answers |
|---|---|
| Overview | How much value is lost, and how far can each headline number be trusted? |
| Waste risk | Which waste events should be prevented first, and why? |
| Demand & events | What did the calendar do to demand, what has it not done yet, and what should be ordered? |
| What-if | What would a prevention lever be worth? (scenario, never a forecast) |
| Data trust | What does the pipeline know, and what does it refuse to claim? |
| Pipeline | From delivery file to published metric, with the reconciliation ledger |

## Architecture

```
delivery files (CSV)
  -> ingestion/contracts.py     source contract: types, nullability, enums, grain, natural key
  -> ingestion/bronze.py        immutable Parquet snapshot + manifest (sha256, row counts)
  -> ingestion/silver.py        validate, normalise, deduplicate, quarantine, publish to warehouse
  -> data/warehouse.duckdb      raw.* (as delivered) and silver.* (cleaned) tables
  -> dbt_project                staging -> intermediate -> dims/facts -> marts
  -> scripts/trust_engine.py    evaluates declared expectations, assigns trust states
  -> scripts/export_marts.py    publish gate: writes data/marts/*.json if open, withdraws the numbers if closed
  -> static dashboard           index.html + data.js + charts.js + views.js + views-ops.js + app.js
```

Two rules shape the design:

1. **No KPI math in the UI.** The browser selects and lays out published values.
   It never computes a metric, never queries the warehouse, and never invents a
   forecast.
2. **Publication is gated.** If a blocking expectation fails, the trust engine
   reports `blocked`, the export removes the previously published numbers, and
   the data routes render the block instead of last run's figures. The trust and
   pipeline pages stay up, because they are what explains the block.

## Quick start

```bash
make install        # python + node dependencies
npx playwright install chromium   # once, for the browser tests
make generate       # write the synthetic delivery files
make pipeline       # deliveries -> warehouse -> trust engine -> published artefacts
make test           # 127 python tests
make test-frontend  # 40 browser checks on the dashboard
make test-a11y      # 43 accessibility and contrast checks
make test-blocked   # prove a blocked gate shows no stale numbers
make test-airflow   # 24 Airflow DAG contract checks
make serve          # http://localhost:4173
```

The dashboard is static. It reads `data/marts/*.json` over HTTP, so it can be
hosted anywhere: `python -m http.server`, nginx, S3, GitHub Pages.

## Airflow (optional)

The pipeline runs from a shell (`make pipeline`). Airflow is the scheduled,
event-driven way to run the *same* pipeline: one DAG, the same scripts, the
same fail-closed rule. It adds a daily schedule, backfill for a missed day, a
retry for a transient warehouse failure (contract failures are never retried),
a sensor that waits for a delivery to land, and an asset
(`wastewise://published/marts`) other DAGs can subscribe to.

```bash
pip install -r requirements-airflow.txt
export WASTEWISE_ROOT=$(pwd)
airflow standalone                    # or: make airflow-up
```

Nothing in the warehouse, the trust engine or the dashboard depends on
Airflow, and the DAG is tested without it installed
(`make airflow-test`). See `airflow/README.md` for the task table, the
configuration and the Docker Compose setup.

## The Data Trust Engine

`mart_dq_expectations` declares 20 expectations next to the models they protect,
in an executable form (`check_spec`). The trust engine evaluates them after every
build and produces:

| Artefact | What it contains |
|---|---|
| `data/marts/trust_report.json` | every expectation with status, severity, owner, remediation; every metric with its trust state, definition and lineage |
| `data/marts/publish_status.json` | the gate: `published` or `blocked` with the blocking reasons |
| `data/marts/lineage.json` | dbt manifest lineage from each model back to the delivery sources |

Expectation kinds: `sql`, `quality_rate`, `source_freshness`, `data_recency`,
`reconciliation`, `dbt_tests`, `dbt_manifest`, `metric_coverage`,
`dashboard_consistency`.

A metric inherits the state of every check that protects its lineage. An estimate
is never promoted to `measured`, and a metric may only be displayed in a state
its registry entry allows.

**Protection is itself checked.** `dq_metric_coverage` verifies that every
published metric comes from a model that either has a dbt test attached or is the
target of a declared expectation. A metric nothing checks is marked `unverified`,
is not displayable, and the export writes `null` instead of a number for it. The
dashboard therefore cannot show a figure that no rule could ever catch breaking.

**Promises are also checked.** `dq_dashboard_consistency` verifies that every
metric the registry promises to the dashboard is actually displayable. If the
data can no longer support a promised metric, the value is withheld and the
check says so instead of the promise quietly going stale.

**Publishing is reproducible.** The same data produces byte-identical
artefacts. Every published table declares the key its rows are sorted by, the
ranks in the marts break ties deterministically, one delivery carries one ingest
timestamp, and the floats are rounded to the precision they are meaningful at. A
diff in `data/marts/` therefore always means a real change. CI rebuilds from
scratch and asserts it; the only fields allowed to differ are the run id, the
timestamps, and the age a freshness check reports.

## The metrics

Definitions live in `mart_metric_registry`, the contract between the warehouse
and every consumer. The current published set:

| Metric | Type | Meaning |
|---|---|---|
| `waste_cost_at_risk` | derived | avoidable recorded waste priced at purchase-unit cost |
| `avoidable_cost_share` | derived | share of waste cost whose reason is classified avoidable |
| `waste_rate_per_demand` | derived | total waste over total demand of the same ingredients, ratio of totals |
| `waste_quantity` | measured | source-recorded waste quantity |
| `units_sold` | measured | point-of-sale units |
| `demand_lift_pct` | derived | measured change in daily units around an event, 7 day window vs 17 day baseline |
| `expected_attendance` | estimated | organiser estimate, confidence carried per event |
| `recommended_order_qty` | estimated | cover days of average demand minus stock on hand |

`waste_rate_per_demand` is a ratio of totals, not an average of daily ratios. The
same data gave 86.5% by averaging and 31.7% as a ratio of totals, because days
with a tiny denominator dominate an average. The published number and the
published definition are now the same thing.

Forward-looking events carry **no** demand lift. An attendance estimate is an
estimate, and the dashboard says so. The purchase plan on the same page is a
planning heuristic with an explainable formula, and it is labelled as such
rather than presented as a demand forecast.

## Repository layout

```
ingestion/        contracts, bronze, silver, synthetic deliveries
dbt_project/      sources, macros, staging, intermediate, dim, facts, marts
scripts/          trust engine, export, reconcile, gate status, local runner
orchestration/    ordered pipeline
airflow/          the scheduled DAG, its image and its compose stack
tests/            python unit tests, browser smoke, a11y audit, blocked-gate test
data/             deliveries, bronze/silver snapshots, warehouse, published artefacts
docs/             architecture, data dictionary, runbook
```

## Commands

```bash
make help          # every target
make dbt-build     # rebuild the warehouse models
make publish       # trust engine + export only
make test-frontend # drive the dashboard in a real browser
make test-a11y     # contrast, heading order, names and focus audit
make test-blocked  # a closed gate renders the block, never stale numbers
make test-airflow  # the Airflow DAG contract, without Airflow installed
make check         # syntax check every python and javascript file
```

## Cost

Local-first: DuckDB is free, the pipeline is a batch job, and nothing has to run
continuously. Snowflake is optional and only used when credentials are present
(`dbt build --target snowflake`); no credentials are ever written to a file.
