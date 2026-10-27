# Airflow

The pipeline runs from a shell (`make pipeline`). Airflow is the scheduled,
event-driven way to run the *same* pipeline, and it is optional: nothing in the
warehouse, the trust engine or the dashboard depends on it.

## What Airflow adds

| Need | Shell (`make pipeline`) | Airflow |
|---|---|---|
| Run on a schedule | cron, and nobody notices when it fails | daily DAG, failed runs visible and alertable |
| Catch up a missed day | run it by hand and hope | `airflow dags backfill` over the interval |
| Retry a transient failure | rerun the whole pipeline | `build_warehouse` is retried twice, contract steps are not |
| Trigger downstream work | wire it by hand | subscribe to the `wastewise://published/marts` asset |
| Wait for a delivery | sleep in a loop | the `wait_for_delivery` sensor waits and records |

## Run it

```bash
# with Docker (needs the project mounted into the scheduler)
docker compose -f airflow/docker-compose.yml up
open http://localhost:8080        # user: airflow, password: airflow

# or on a machine that already has Airflow
pip install -r requirements-airflow.txt
export WASTEWISE_ROOT=$(pwd)
airflow standalone
```

Then trigger the DAG by hand:

```bash
airflow dags trigger wastewise_pipeline
airflow dags list-import-errors          # the DAG has to parse
```

## The DAG

`airflow/dags/wastewise_pipeline.py`

```
deliver -> wait_for_delivery -> ingest -> reconcile -> build_warehouse
        -> evaluate_gate -> publish -> gate_status
```

| Task | Script | Notes |
|---|---|---|
| `deliver` | `ingestion/generate_synthetic.py` | skipped when `WASTEWISE_SYNTHETIC=0` |
| `wait_for_delivery` | sensor | waits for a delivery newer than the last one the DAG saw |
| `ingest` | `scripts/run_local_pipeline.py` | bronze, contract validation, silver |
| `reconcile` | `scripts/reconcile.py` | delivered versus published ledger |
| `build_warehouse` | `dbt build --profiles-dir .` | 2 retries: a transient warehouse failure is not a data failure |
| `evaluate_gate` | `scripts/trust_engine.py` | fails when a blocking expectation breaks |
| `publish` | `scripts/export_marts.py` | publishes, or withdraws the numbers when the gate is closed |
| `gate_status` | `scripts/gate_status.py` | exit code 2 means the gate is closed and the numbers were withdrawn |

`publish` and `gate_status` use the `all_done` trigger rule. A refused trust
run still has to withdraw the numbers that were published before, and the run
still has to report the closed gate. This is the same fail-closed rule the
local runner follows.

## Assets

Other DAGs can subscribe to these and run when the numbers are published:

| Asset | Produced by |
|---|---|
| `wastewise://warehouse/silver` | `build_warehouse` |
| `wastewise://warehouse/marts` | `evaluate_gate` |
| `wastewise://published/marts` | `publish` |

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `WASTEWISE_ROOT` | `/opt/wastewise` | where the project lives inside the scheduler |
| `WASTEWISE_PYTHON` | `python3` | the interpreter that runs the pipeline scripts |
| `WASTEWISE_SYNTHETIC` | `1` | write the synthetic delivery files before waiting |
| `WASTEWISE_WAIT_FOR_DELIVERY` | `1` | wait for a new delivery instead of reusing the last one |
| `WASTEWISE_SCHEDULE` | `0 5 * * *` | the cron schedule |

## Tests

The DAG is a promise about task order, retries and the fail-closed rule, so it
is tested without Airflow installed: `tests/test_airflow_dag.py` puts
recording stubs in `sys.modules`, imports the DAG file and asserts the
structure.

```bash
make airflow-test
```
