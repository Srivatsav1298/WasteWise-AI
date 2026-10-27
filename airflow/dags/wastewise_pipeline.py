"""WasteWiseAI as an Airflow DAG: delivery to published metric.

Why Airflow here
----------------
The pipeline already runs from a shell (``make pipeline``). Airflow adds the
three things a scheduled platform needs and a shell does not:

- a schedule and a backfill. The pipeline runs daily, and a missed day can be
  replayed without touching the warehouse by hand;
- assets. The numbers the dashboard serves are published as an asset, so any
  downstream DAG (a report, a notification, a retrained model) runs when new
  numbers are published and not before;
- per-stage failure handling. A transient warehouse failure is retried, a
  contract failure is not, and the publish step runs whatever happened before
  it.

The contract of the pipeline does not change. Every task calls the same
scripts the local runner calls, in the same order, and the publish step still
withdraws the previously published numbers when the gate is closed.

Task order
----------
    deliver -> wait_for_delivery -> ingest -> reconcile -> build_warehouse
            -> evaluate_gate -> publish -> gate_status

``publish`` and ``gate_status`` run with the ``all_done`` trigger rule: a
refused trust run still has to withdraw the numbers, and the run still has to
report the closed gate.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

# --- Airflow compatibility -------------------------------------------------
# Airflow 3 moved the task SDK to ``airflow.sdk`` and the core operators into
# the standard provider. Airflow 2 has neither. This file has to parse on
# both, so every import falls back on its own.
try:
    from airflow import DAG
except ImportError:  # pragma: no cover - Airflow 3 without the legacy alias
    from airflow.sdk import DAG

try:
    from airflow.sdk import Asset
except ImportError:  # Airflow 2
    from airflow.datasets import Dataset as Asset

try:
    from airflow.sdk import BaseSensorOperator
except ImportError:  # Airflow 2
    from airflow.sensors.base import BaseSensorOperator

try:
    from airflow.providers.standard.operators.bash import BashOperator
except ImportError:  # Airflow 2
    from airflow.operators.bash import BashOperator


ROOT = Path(os.environ.get("WASTEWISE_ROOT", "/opt/wastewise"))
PYTHON = os.environ.get("WASTEWISE_PYTHON", "python3")
DBT_DIR = ROOT / "dbt_project"
RAW_DIR = ROOT / "data" / "raw"
DELIVERY_STATE = RAW_DIR / ".delivery_state.json"

# The assets other DAGs can subscribe to.
SILVER = Asset("wastewise://warehouse/silver")
MARTS = Asset("wastewise://warehouse/marts")
PUBLISHED = Asset("wastewise://published/marts")

DOC_MD = """
## WasteWiseAI publishing pipeline

Each run takes a delivery through the warehouse, the Data Trust Engine and the
publication gate, and publishes the numbers only when the gate is open.

| Task | What it does | Retries |
|---|---|---|
| `deliver` | writes the synthetic delivery files (set `WASTEWISE_SYNTHETIC=0` and drop your own files in `data/raw`) | 0 |
| `wait_for_delivery` | waits for a delivery newer than the last one this DAG saw | n/a |
| `ingest` | bronze snapshot, contract validation, silver publication | 0 |
| `reconcile` | writes the delivered-versus-published ledger | 0 |
| `build_warehouse` | `dbt build`: staging, facts, dimensions, marts and their tests | 2 |
| `evaluate_gate` | evaluates the declared expectations and assigns trust states | 0 |
| `publish` | writes `data/marts/*.json`, or withdraws the numbers when the gate is closed | 0 |
| `gate_status` | reports the gate: green when the numbers are published, red when they were withdrawn | 0 |

`publish` and `gate_status` run even when `evaluate_gate` fails. That is the
point: a failed gate has to remove the numbers that were published before, not
leave them on disk.

### Assets

| Asset | Produced by | Consumed by |
|---|---|---|
| `wastewise://warehouse/silver` | `build_warehouse` | anything that needs the cleaned sources |
| `wastewise://warehouse/marts` | `evaluate_gate` | anything that needs the modelled tables |
| `wastewise://published/marts` | `publish` | the dashboard, and any downstream report |

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `WASTEWISE_ROOT` | `/opt/wastewise` | where the project lives inside the scheduler |
| `WASTEWISE_PYTHON` | `python3` | the interpreter that runs the pipeline scripts |
| `WASTEWISE_SYNTHETIC` | `1` | write the synthetic delivery files before waiting |
| `WASTEWISE_WAIT_FOR_DELIVERY` | `1` | wait for a new delivery instead of running on the last one |
| `WASTEWISE_SCHEDULE` | `0 5 * * *` | the cron schedule, 05:00 every day |
"""


# --- delivery helpers ------------------------------------------------------
# These are deliberately plain functions: they carry the logic the sensor
# depends on and they can be tested without Airflow running.


def delivery_files(raw_dir: Path) -> List[Path]:
    """The delivery files currently in the raw directory."""
    return sorted(Path(raw_dir).glob("*.csv"))


def newest_delivery_mtime(raw_dir: Path) -> float:
    """The newest modification time among the delivery files."""
    files = delivery_files(raw_dir)
    return max((path.stat().st_mtime for path in files), default=0.0)


def has_new_delivery(raw_dir: Path, state_path: Path) -> bool:
    """True when a delivery is newer than the one this DAG last saw.

    The state file records the newest delivery of the last run. Without it,
    any delivery counts as new: the first run has nothing to compare against.
    """
    files = delivery_files(raw_dir)
    if not files:
        return False
    newest = max(path.stat().st_mtime for path in files)
    state_path = Path(state_path)
    if not state_path.exists():
        return True
    try:
        state = json.loads(state_path.read_text())
        seen = float(state.get("seen_mtime", 0.0))
    except (OSError, ValueError, TypeError):
        return True
    return newest > seen


def remember_delivery(raw_dir: Path, state_path: Path) -> None:
    """Record the delivery this run consumed, so the next run waits for a new one."""
    files = delivery_files(raw_dir)
    if not files:
        return
    newest = max(files, key=lambda path: path.stat().st_mtime)
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "file": newest.name,
                "seen_mtime": newest.stat().st_mtime,
                "seen_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            indent=2,
        )
    )


class DeliverySensor(BaseSensorOperator):
    """Wait until a delivery lands in ``data/raw``.

    This is the event-driven entry point of the DAG: the run waits here until
    a delivery file is newer than the last one the DAG saw, and it records
    that delivery so the next run waits for the next one instead of rebuilding
    the same numbers.
    """

    def __init__(self, raw_dir: str, state_path: str, **kwargs):
        super().__init__(**kwargs)
        self.raw_dir = Path(raw_dir)
        self.state_path = Path(state_path)

    def poke(self, context) -> bool:
        if os.environ.get("WASTEWISE_WAIT_FOR_DELIVERY", "1") != "1":
            return True
        if not has_new_delivery(self.raw_dir, self.state_path):
            return False
        remember_delivery(self.raw_dir, self.state_path)
        return True


# --- the pipeline ----------------------------------------------------------

with DAG(
    dag_id="wastewise_pipeline",
    description="Delivery to published metric, gated by the Data Trust Engine",
    schedule=os.environ.get("WASTEWISE_SCHEDULE", "0 5 * * *"),
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "data-platform",
        "retries": 0,
        "retry_delay": timedelta(minutes=5),
        "execution_timeout": timedelta(hours=2),
    },
    doc_md=DOC_MD,
    tags=["wastewise", "publishing", "trust"],
) as dag:
    deliver = BashOperator(
        task_id="deliver",
        retries=0,
        bash_command=(
            'if [ "${WASTEWISE_SYNTHETIC:-1}" = "1" ]; then '
            f"cd {ROOT} && {PYTHON} ingestion/generate_synthetic.py; "
            'else echo "synthetic delivery skipped: WASTEWISE_SYNTHETIC=0"; fi'
        ),
        doc_md="Write the synthetic delivery files. A real deployment sets WASTEWISE_SYNTHETIC=0 and drops its own files into data/raw.",
    )

    wait_for_delivery = DeliverySensor(
        task_id="wait_for_delivery",
        retries=0,
        raw_dir=str(RAW_DIR),
        state_path=str(DELIVERY_STATE),
        poke_interval=60,
        timeout=6 * 60 * 60,
        mode="reschedule",
        doc_md="Wait for a delivery newer than the last one this DAG consumed.",
    )

    ingest = BashOperator(
        task_id="ingest",
        retries=0,
        bash_command=f"cd {ROOT} && {PYTHON} scripts/run_local_pipeline.py",
        doc_md="Bronze snapshot, contract validation, deduplication, quarantine and silver publication.",
    )

    reconcile = BashOperator(
        task_id="reconcile",
        retries=0,
        bash_command=f"cd {ROOT} && {PYTHON} scripts/reconcile.py",
        doc_md="Write the delivered-versus-published ledger the trust engine compares against.",
    )

    build_warehouse = BashOperator(
        task_id="build_warehouse",
        bash_command=f"cd {DBT_DIR} && dbt build --profiles-dir .",
        retries=2,
        retry_delay=timedelta(minutes=2),
        outlets=[SILVER, MARTS],
        doc_md="Build every dbt model and run every dbt test. A transient warehouse failure is retried; a failing test is not.",
    )

    evaluate_gate = BashOperator(
        task_id="evaluate_gate",
        retries=0,
        bash_command=f"cd {ROOT} && {PYTHON} scripts/trust_engine.py",
        outlets=[MARTS],
        doc_md="Evaluate the declared expectations and assign a trust state to every metric. Fails when a blocking expectation breaks.",
    )

    publish = BashOperator(
        task_id="publish",
        retries=0,
        bash_command=(
            # set -e: when the gate is open the export has to succeed or the
            # task is red. Without it a failing export would be hidden by the
            # verdict of the next line.
            "set -eu\n"
            f"cd {ROOT}\n"
            "# The gate verdict of this run is the one the trust engine just wrote.\n"
            "# When it is open the export has to succeed or the task is red; when it\n"
            "# is closed the export refuses and withdraws the numbers it published\n"
            "# before, and that refusal is the expected outcome.\n"
            f"gate=$({PYTHON} scripts/gate_status.py --state || true)\n"
            'if [ "$gate" = "published" ]; then\n'
            f"  {PYTHON} scripts/export_marts.py\n"
            "else\n"
            f"  {PYTHON} scripts/export_marts.py || echo 'export refused: the gate is closed'\n"
            "fi\n"
            f"{PYTHON} scripts/gate_status.py --tolerate-blocked"
        ),
        trigger_rule="all_done",
        outlets=[PUBLISHED],
        doc_md="Publish data/marts/*.json when the gate is open, withdraw the previous numbers when it is closed.",
    )

    gate_status = BashOperator(
        task_id="gate_status",
        retries=0,
        bash_command=f"cd {ROOT} && {PYTHON} scripts/gate_status.py",
        trigger_rule="all_done",
        doc_md="Report the gate. Exit code 2 means the gate is closed and the numbers were withdrawn.",
    )

    deliver >> wait_for_delivery >> ingest >> reconcile >> build_warehouse >> evaluate_gate >> publish >> gate_status
