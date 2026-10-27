"""Contract test for the Airflow DAG. It runs without Airflow installed.

The DAG is a promise about the order of the pipeline, about what is retried
and about the fail-closed rule. Airflow is a heavy dependency and the repo
does not need it to test that promise, so the Airflow imports are replaced by
recording stubs and the structure is asserted instead.

If Airflow is installed, the stubs still win: they are put in ``sys.modules``
before the DAG file is imported, so the test measures the same thing on every
machine.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAG_FILE = ROOT / "airflow" / "dags" / "wastewise_pipeline.py"


class _StubOperator:
    """Records what a task was configured with and how it was wired."""

    def __init__(self, task_id=None, **kwargs):
        self.task_id = task_id
        self.kwargs = kwargs
        self.upstream = []
        self.downstream = []
        dag = _CURRENT.get("dag")
        if dag is not None:
            dag.tasks.append(self)

    def __rshift__(self, other):
        self.downstream.append(other)
        other.upstream.append(self)
        return other

    def __rrshift__(self, other):
        other.downstream.append(self)
        self.upstream.append(other)
        return self


class _StubDAG:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.tasks = []
        _CURRENT["dag"] = self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        _CURRENT["dag"] = None
        return False


_CURRENT = {"dag": None}


def _module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


class _StubAsset:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, _StubAsset) and other.name == self.name

    def __hash__(self):
        return hash(self.name)


def _install_airflow_stubs():
    """Put a recording Airflow in sys.modules and return the undo list."""
    saved = {name: module for name, module in sys.modules.items() if name == "airflow" or name.startswith("airflow.")}

    _module("airflow", DAG=_StubDAG)
    _module("airflow.sdk", Asset=_StubAsset, BaseSensorOperator=_StubOperator)
    _module("airflow.datasets", Dataset=_StubAsset)
    _module("airflow.sensors")
    _module("airflow.sensors.base", BaseSensorOperator=_StubOperator)
    _module("airflow.operators")
    _module("airflow.operators.bash", BashOperator=_StubOperator)
    _module("airflow.providers")
    _module("airflow.providers.standard")
    _module("airflow.providers.standard.operators")
    _module("airflow.providers.standard.operators.bash", BashOperator=_StubOperator)
    return saved


def _restore_airflow(saved):
    for name in [name for name in sys.modules if name == "airflow" or name.startswith("airflow.")]:
        del sys.modules[name]
    sys.modules.update(saved)


def _load_dag():
    saved = _install_airflow_stubs()
    try:
        spec = importlib.util.spec_from_file_location("wastewise_pipeline_dag", DAG_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        _restore_airflow(saved)


class DagStructureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_dag()
        cls.dag = cls.module.dag
        cls.tasks = {task.task_id: task for task in cls.dag.tasks}

    def test_every_step_of_the_pipeline_is_a_task(self):
        for task_id in (
            "deliver",
            "wait_for_delivery",
            "ingest",
            "reconcile",
            "build_warehouse",
            "evaluate_gate",
            "publish",
            "gate_status",
        ):
            self.assertIn(task_id, self.tasks)

    def test_the_tasks_run_in_the_order_of_the_pipeline(self):
        order = [
            "deliver",
            "wait_for_delivery",
            "ingest",
            "reconcile",
            "build_warehouse",
            "evaluate_gate",
            "publish",
            "gate_status",
        ]
        for upstream_id, downstream_id in zip(order, order[1:]):
            upstream = self.tasks[upstream_id]
            downstream = self.tasks[downstream_id]
            self.assertIn(
                downstream,
                upstream.downstream,
                f"{upstream_id} should run before {downstream_id}",
            )

    def test_the_publish_step_runs_even_when_the_gate_refuses(self):
        publish = self.tasks["publish"]
        self.assertEqual(publish.kwargs["trigger_rule"], "all_done")

    def test_the_gate_status_runs_even_when_the_gate_refuses(self):
        self.assertEqual(self.tasks["gate_status"].kwargs["trigger_rule"], "all_done")

    def test_a_transient_warehouse_failure_is_retried_and_a_contract_failure_is_not(self):
        self.assertEqual(self.tasks["build_warehouse"].kwargs["retries"], 2)
        self.assertEqual(self.tasks["ingest"].kwargs["retries"], 0)
        self.assertEqual(self.tasks["evaluate_gate"].kwargs["retries"], 0)

    def test_the_tasks_call_the_scripts_the_local_runner_calls(self):
        commands = " ".join(
            str(task.kwargs.get("bash_command", "")) for task in self.dag.tasks
        )
        for script in (
            "ingestion/generate_synthetic.py",
            "scripts/run_local_pipeline.py",
            "scripts/reconcile.py",
            "scripts/trust_engine.py",
            "scripts/export_marts.py",
            "scripts/gate_status.py",
        ):
            self.assertIn(script, commands)
        self.assertIn("dbt build --profiles-dir .", commands)

    def test_the_published_numbers_are_an_asset_other_dags_can_wait_for(self):
        outlets = self.tasks["publish"].kwargs["outlets"]
        names = [outlet.name for outlet in outlets]
        self.assertIn("wastewise://published/marts", names)

    def test_the_dag_runs_on_a_schedule_without_overlapping_itself(self):
        self.assertEqual(self.dag.kwargs["max_active_runs"], 1)
        self.assertEqual(self.dag.kwargs["schedule"], "0 5 * * *")


class PublishTaskBehaviourTest(unittest.TestCase):
    """The publish task runs for real, in a sandbox copy of the project.

    The fail-closed rule lives in this command: a closed gate has to withdraw
    the numbers, and a broken export must not be hidden behind a green verdict.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wastewise-publish-"))
        shutil.copytree(ROOT / "scripts", self.tmp / "scripts")
        (self.tmp / "data").mkdir()
        shutil.copytree(ROOT / "data" / "marts", self.tmp / "data" / "marts")
        warehouse = ROOT / "data" / "warehouse.duckdb"
        if warehouse.exists():
            shutil.copy(warehouse, self.tmp / "data" / "warehouse.duckdb")
        self.original_root = os.environ.get("WASTEWISE_ROOT")
        os.environ["WASTEWISE_ROOT"] = str(self.tmp)
        self.module = _load_dag()
        self.command = self.module.publish.kwargs["bash_command"]

    def tearDown(self):
        if self.original_root is None:
            os.environ.pop("WASTEWISE_ROOT", None)
        else:
            os.environ["WASTEWISE_ROOT"] = self.original_root
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self):
        return subprocess.run(
            ["bash", "-c", self.command],
            capture_output=True,
            text=True,
        )

    def _status(self, status):
        (self.tmp / "data" / "marts" / "publish_status.json").write_text(
            json.dumps({"status": status, "blockers": []})
        )

    def _measurements(self):
        """The measurement artefacts, the ones a closed gate has to withdraw."""
        from scripts.export_marts import MEASUREMENT_STEMS

        return sorted(
            path.name
            for path in (self.tmp / "data" / "marts").glob("*.json")
            if path.stem in MEASUREMENT_STEMS
        )

    def test_an_open_gate_publishes_and_the_task_succeeds(self):
        self._status("published")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self._measurements())

    def test_a_closed_gate_withdraws_the_numbers_and_the_task_succeeds(self):
        self._status("blocked")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._measurements(), [])

    def test_a_closed_gate_keeps_the_diagnostics(self):
        self._status("blocked")
        self._run()
        names = sorted(path.name for path in (self.tmp / "data" / "marts").glob("*.json"))
        self.assertIn("publish_status.json", names)
        self.assertIn("trust_report.json", names)

    def test_a_broken_export_behind_an_open_gate_fails_the_task(self):
        self._status("published")
        (self.tmp / "data" / "warehouse.duckdb").unlink(missing_ok=True)
        result = self._run()
        self.assertNotEqual(result.returncode, 0)


class DeliverySensorTest(unittest.TestCase):
    """The sensor logic is plain python and is tested without Airflow."""

    def setUp(self):
        self.module = _load_dag()
        self.tmp = Path(tempfile.mkdtemp(prefix="wastewise-delivery-"))
        self.raw = self.tmp / "raw"
        self.raw.mkdir()
        self.state = self.raw / ".delivery_state.json"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, mtime):
        path = self.raw / name
        path.write_text("id\n1\n")
        import os

        os.utime(path, (mtime, mtime))
        return path

    def test_a_first_delivery_counts_as_new(self):
        self._write("sales.csv", 1000.0)
        self.assertTrue(self.module.has_new_delivery(self.raw, self.state))

    def test_the_same_delivery_does_not_count_as_new_twice(self):
        self._write("sales.csv", 1000.0)
        self.assertTrue(self.module.has_new_delivery(self.raw, self.state))
        self.module.remember_delivery(self.raw, self.state)
        self.assertFalse(self.module.has_new_delivery(self.raw, self.state))

    def test_a_newer_delivery_counts_as_new(self):
        self._write("sales.csv", 1000.0)
        self.module.remember_delivery(self.raw, self.state)
        self._write("waste_events.csv", 2000.0)
        self.assertTrue(self.module.has_new_delivery(self.raw, self.state))

    def test_an_empty_raw_directory_is_not_a_delivery(self):
        self.assertFalse(self.module.has_new_delivery(self.raw, self.state))

    def test_the_state_file_records_the_delivery_it_saw(self):
        self._write("sales.csv", 1000.0)
        self.module.remember_delivery(self.raw, self.state)
        state = json.loads(self.state.read_text())
        self.assertEqual(state["file"], "sales.csv")
        self.assertEqual(state["seen_mtime"], 1000.0)


class GateStatusTest(unittest.TestCase):
    """The gate report the DAG ends on."""

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        from scripts import gate_status

        self.module = gate_status
        self.tmp = Path(tempfile.mkdtemp(prefix="wastewise-gate-"))
        self.original_mart = gate_status.MART
        gate_status.MART = self.tmp

    def tearDown(self):
        import shutil

        self.module.MART = self.original_mart
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, payload):
        (self.tmp / name).write_text(json.dumps(payload))

    def test_a_missing_status_is_a_failure(self):
        self.assertIsNone(self.module.read_gate()["status"])

    def test_a_closed_gate_lists_its_blockers(self):
        self._write(
            "publish_status.json",
            {"status": "blocked", "blockers": [{"check_id": "dq_x", "message": "broken"}]},
        )
        gate = self.module.read_gate()
        self.assertEqual(gate["status"], "blocked")
        self.assertEqual(gate["blockers"][0]["check_id"], "dq_x")

    def test_an_unprotected_published_metric_is_reported(self):
        self._write("publish_status.json", {"status": "published", "blockers": []})
        self._write(
            "trust_report.json",
            {
                "summary": {"checks_passed": 20, "checks_total": 20},
                "metrics": [
                    {"metric_key": "waste_cost_at_risk", "published": True, "protected": False}
                ],
            },
        )
        gate = self.module.read_gate()
        self.assertEqual(gate["unprotected_metrics"], ["waste_cost_at_risk"])

    def _main(self, argv):
        import io
        from contextlib import redirect_stdout

        saved_argv = sys.argv
        sys.argv = ["gate_status.py"] + argv
        try:
            with redirect_stdout(io.StringIO()):
                return self.module.main()
        finally:
            sys.argv = saved_argv

    def test_a_closed_gate_exits_with_two(self):
        self._write(
            "publish_status.json",
            {"status": "blocked", "blockers": [{"check_id": "dq_x", "message": "broken"}]},
        )
        self.assertEqual(self._main([]), 2)

    def test_a_closed_gate_can_be_tolerated_by_the_publish_step(self):
        self._write(
            "publish_status.json",
            {"status": "blocked", "blockers": [{"check_id": "dq_x", "message": "broken"}]},
        )
        self.assertEqual(self._main(["--tolerate-blocked"]), 0)

    def test_an_open_gate_exits_with_zero(self):
        self._write("publish_status.json", {"status": "published", "blockers": []})
        self._write("trust_report.json", {"summary": {"checks_passed": 20, "checks_total": 20}, "metrics": []})
        self.assertEqual(self._main([]), 0)

    def test_a_missing_status_exits_with_one(self):
        self.assertEqual(self._main([]), 1)


if __name__ == "__main__":
    unittest.main()
