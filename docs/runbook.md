# Runbook

## Normal run

```bash
make install      # once
make generate     # write the synthetic delivery files
make pipeline     # deliveries -> warehouse -> trust engine -> published artefacts
make test         # python test suite
make serve        # dashboard on http://localhost:4173
```

`make pipeline` runs six steps in order and stops at the first failure:

1. `deliver` — write the delivery files
2. `bronze+silver` — snapshot to bronze, then validate, normalise, deduplicate, quarantine and publish to the warehouse
3. `reconcile` — compare delivered rows against published rows
4. `dbt build` — build every model and run every test
5. `trust engine` — evaluate the declared expectations, assign trust states
6. `publish` — write `data/marts/*.json` if the gate is open; withdraw the published numbers if it is closed

Expected result: `{"status": "success", "message": "pipeline completed"}`, a
trust report of `20/20` passing expectations, and `publish_status.json` with
`"status": "published"`.

## Checking the result

```bash
cat data/marts/publish_status.json     # the gate
cat data/marts/trust_report.json       # expectations and metric trust states
cat data/marts/reconciliation.json     # delivered vs published
cat data/marts/run_metadata.json       # the run
```

The dashboard shows the same state. If the gate is closed, the masthead reads
"Publication blocked" and the trust page lists the failing expectations.

## Reproducibility

The pipeline is deterministic: the same source data produces byte-identical
artefacts, apart from the run id, the timestamps, and the age that a freshness
check reports. If `data/marts/` changes after a rebuild that should not have
changed anything, something in the pipeline stopped being deterministic. The
usual causes are a new table published without an `order by`, a rank that does
not break ties on the full grain, an `any_value` aggregate, or a per-source
ingest timestamp that lets the clock decide which source is the oldest.

```bash
make clean && make pipeline        # rebuild everything
git diff --stat data/marts         # only run ids, timestamps and ages should change
```

To compare two runs the way CI does:

```bash
cp -r data/marts /tmp/first_run
make clean && make pipeline
python scripts/check_reproducible.py /tmp/first_run data/marts
```

The comparison ignores the run id, the timestamps, the paths that embed the
run id, the observed values and the age inside a freshness message. Every other
difference is drift.

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| `missing columns` | the delivery does not match its contract | fix the source; never bypass the contract |
| `invalid numeric/date` | a value cannot be cast | the row is quarantined with a reason; correct the source |
| `publish blocked` | a blocking expectation failed | open `data/marts/trust_report.json`, find the `fail` entry, read its `remediation`. The published numbers have been removed on purpose; fix the cause, then run `make pipeline` again |
| the dashboard shows "Publication blocked" on every data page | the gate is closed, so the numbers were withdrawn | this is the intended fail-closed state; the trust console lists the failing expectation and its remediation |
| `no publish status found` | the trust engine has not run | `python scripts/trust_engine.py` |
| a metric shows as uncovered | its source model has no dbt test and no expectation | add a test to `dbt_project/models/schema.yml` or an expectation to `mart_dq_expectations.sql` |
| a metric is promised to the dashboard but not shown | its trust state no longer allows it, so the export withheld the value | read the `dq_dashboard_consistency` entry in the trust report; widen the allowed trust states in `mart_metric_registry.sql` or stop promising the metric |
| dashboard shows a load error | the artefacts are missing or stale | `make pipeline`, then reload |
| `dbt` connection error | the warehouse is locked by another process | close any open DuckDB connection, then `make dbt-build` |
| source freshness failure | a delivery is older than the declared window | re-deliver the source; the warning threshold is 12h, the error threshold 3d |

## Adding a metric

1. Add or change the model in `dbt_project/models/marts/`.
2. Register the metric in `mart_metric_registry.sql`: definition, numerator,
   denominator, unit, measurement type, allowed trust states, owner, caveat.
3. Protect it. Either add a dbt test for the model in
   `dbt_project/models/schema.yml`, or add an expectation to
   `mart_dq_expectations.sql` that targets the model. `dq_metric_coverage`
   fails the gate if you do neither.
4. Export it in `scripts/export_marts.py`.
5. Render it in the dashboard from the exported artefact. No metric may be
   computed in the browser.
6. `make pipeline && make test`.

## Changing a business rule

Business rules live in `dbt_project/dbt_project.yml` as vars
(`avoidable_reasons`, `min_coverage_for_ranking`, `priority_tier_high`,
`priority_tier_medium`, `target_cover_days`) or in `dim_waste_reason`. A rule
change is a data change, so it goes through the pipeline and the trust engine
like any other.

## Airflow (optional)

The DAG is the scheduled form of the same pipeline. Run it from Airflow
(`airflow dags trigger wastewise_pipeline`) or from the shell
(`make pipeline`); both publish the same artefacts.

| Symptom | Cause | Action |
|---|---|---|
| the DAG is red at `evaluate_gate` | a blocking expectation failed | read the `BLOCKER` lines in the task log, fix the cause, rerun. The numbers were withdrawn on purpose |
| the DAG is red at `gate_status` | the gate is closed | same cause; `python scripts/gate_status.py` prints the blockers and the remediation |
| the DAG is red at `publish` | the export could not run | check that the warehouse exists and that `data/marts` is writable by the scheduler user |
| `wait_for_delivery` never finishes | no delivery newer than the last one | drop the delivery files into `data/raw`, or set `WASTEWISE_WAIT_FOR_DELIVERY=0` to run on the last delivery |
| the DAG does not appear in Airflow | the DAG file failed to parse | `airflow dags list-import-errors`; the contract test is `make airflow-test` |

## Snowflake (optional)

Set the environment variables from `.env.example` and build against the
`snowflake` target. Credentials are read from the environment only and are
never written to a file. The local DuckDB path stays the default.

The Snowflake loader (`warehouse/load_snowflake.py`) uploads `data/clean/*.csv`,
which the local runner writes for it.

## Spark (optional)

`pyspark_jobs/clean_operational_data.py` is a scale-out path for deliveries that
are too large for the local runner. It is not part of the default pipeline and it
does not enforce the source contract, so it never replaces
`ingestion/silver.py`. Install it with `pip install -r requirements-spark.txt`.

## Legacy artefacts

The pre-dbt reason mart is written to `data/legacy/waste_by_reason.csv`, never
to `data/marts/`. `data/marts/` holds only artefacts the trust engine approved:
if a file is in that folder, it passed the gate.

## Docker

```bash
docker build -t wastewiseai .
docker run --rm -p 4173:4173 wastewiseai
```

The container runs the pipeline before serving the dashboard, so the artefacts
on screen always come from the same image. Set `WASTEWISE_SKIP_PIPELINE=1` to
serve pre-built artefacts instead.
