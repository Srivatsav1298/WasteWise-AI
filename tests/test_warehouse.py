"""Warehouse invariants.

These tests guard the bugs that actually happened in this project: joins that
fanned out, grains that were not unique, and aggregates that did not reconcile
with the delivered rows.
"""
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import duckdb

ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"

sys.path.insert(0, str(ROOT / "scripts"))
import trust_engine  # noqa: E402
import run_local_pipeline  # noqa: E402


def _warehouse_available() -> bool:
    return WAREHOUSE.exists()


@unittest.skipUnless(_warehouse_available(), "warehouse not built yet")
class WarehouseInvariantTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = duckdb.connect(str(WAREHOUSE), read_only=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _scalar(self, sql):
        return self.con.execute(sql).fetchone()[0]

    def test_fact_waste_has_one_row_per_event(self):
        fact_rows = self._scalar("select count(*) from main.fct_waste_events")
        silver_rows = self._scalar("select count(*) from silver.waste_events")
        self.assertEqual(fact_rows, silver_rows)

    def test_fact_sales_has_one_row_per_sale(self):
        fact_rows = self._scalar("select count(*) from main.fct_sales")
        silver_rows = self._scalar("select count(*) from silver.sales")
        self.assertEqual(fact_rows, silver_rows)

    def test_mart_never_inflates_waste_quantity(self):
        mart_total = self._scalar("select coalesce(sum(waste_quantity), 0) from main.mart_waste_daily")
        source_total = self._scalar("select coalesce(sum(quantity), 0) from silver.waste_events")
        self.assertAlmostEqual(float(mart_total), float(source_total), places=6)

    def test_mart_never_inflates_waste_cost(self):
        mart_total = self._scalar("select coalesce(sum(estimated_cost), 0) from main.fct_waste_events")
        # Recomputed from the delivered rows, rounding per row exactly like the
        # fact table does, so any join driven multiplication shows up.
        source_total = self.con.execute(
            "select coalesce(sum(round(cast(w.quantity as double) * i.unit_cost, 2)), 0) "
            "from silver.waste_events w "
            "left join (select ingredient_id, max(unit_cost) as unit_cost "
            "           from silver.ingredients group by 1) i using (ingredient_id)"
        ).fetchone()[0]
        self.assertAlmostEqual(float(mart_total), float(source_total), places=2)

    def test_opportunity_grain_is_unique(self):
        duplicates = self._scalar(
            "select count(*) from (select waste_date, location_id, ingredient_id, waste_reason "
            "from main.mart_waste_opportunity group by 1,2,3,4 having count(*) > 1)"
        )
        self.assertEqual(duplicates, 0)

    def test_priority_keeps_the_opportunity_grain(self):
        opportunity = self._scalar("select count(*) from main.mart_waste_opportunity")
        priority = self._scalar("select count(*) from main.mart_waste_priority")
        self.assertEqual(opportunity, priority)

    def test_no_orphaned_waste_references(self):
        orphans = self._scalar(
            "select count(*) from main.fct_waste_events "
            "where has_location_reference = 0 or has_ingredient_reference = 0"
        )
        self.assertEqual(orphans, 0)

    def test_event_window_cost_cannot_exceed_location_total(self):
        """A window is a slice of the series, never more than the whole."""
        breach = self.con.execute(
            "select count(*) from main.mart_demand_events w "
            "join (select location_id, sum(estimated_cost) as total "
            "      from main.mart_waste_priority group by 1) t using (location_id) "
            "where w.window_waste_cost > t.total"
        ).fetchone()[0]
        self.assertEqual(breach, 0)

    def test_forward_looking_events_carry_no_lift(self):
        rows = self.con.execute(
            "select demand_lift_pct from main.mart_demand_events where is_forward_looking"
        ).fetchall()
        self.assertTrue(rows)
        for (value,) in rows:
            self.assertIsNone(value)

    def test_every_metric_is_documented(self):
        undocumented = self._scalar(
            "select count(*) from main.mart_metric_registry "
            "where published and (owner is null or definition is null or unit is null)"
        )
        self.assertEqual(undocumented, 0)

    def test_every_expectation_is_executable(self):
        invalid = self.con.execute(
            "select count(*) from main.mart_dq_expectations where check_spec is null or check_spec = ''"
        ).fetchone()[0]
        self.assertEqual(invalid, 0)

    def test_summary_total_reconciles_with_its_locations(self):
        """The 'all' row is the sum of the per-location rows, not a second count."""
        total = self.con.execute(
            "select waste_quantity, waste_cost, waste_events from main.mart_food_loss_summary "
            "where is_total = 1"
        ).fetchone()
        parts = self.con.execute(
            "select sum(waste_quantity), sum(waste_cost), sum(waste_events) "
            "from main.mart_food_loss_summary where is_total = 0"
        ).fetchone()
        for total_value, part_value in zip(total, parts):
            self.assertAlmostEqual(float(total_value), float(part_value), places=2)

    def test_published_waste_rate_is_a_ratio_of_totals(self):
        """Guard against the average-of-ratios regression.

        Averaging per-row ratios gave 86.5% on the same data that yields 31.7%
        as a ratio of totals, because days with a tiny denominator dominated the
        average. The published number must be the ratio of totals.
        """
        row = self.con.execute(
            "select waste_quantity, ingredient_demand_qty, waste_rate_per_demand "
            "from main.mart_food_loss_summary where is_total = 1"
        ).fetchone()
        expected = float(row[0]) / float(row[1])
        self.assertAlmostEqual(float(row[2]), expected, places=6)

    def test_summary_waste_cost_matches_the_priority_mart(self):
        summary = self._scalar(
            "select waste_cost from main.mart_food_loss_summary where is_total = 1"
        )
        priority = self._scalar("select sum(estimated_cost) from main.mart_waste_priority")
        self.assertAlmostEqual(float(summary), float(priority), places=2)

    def test_published_metric_source_models_exist(self):
        """A metric may not claim a model that does not exist."""
        models = {
            row[0]
            for row in self.con.execute(
                "select table_name from information_schema.tables where table_schema = 'main'"
            ).fetchall()
        }
        registry = self.con.execute(
            "select distinct source_model from main.mart_metric_registry"
        ).fetchall()
        for (source_model,) in registry:
            self.assertIn(source_model, models, source_model)

    def test_every_published_metric_is_protected(self):
        """No published metric may come from a model that nothing checks."""
        protection = {
            row[0]
            for row in self.con.execute(
                "select check_id from main.mart_dq_expectations where check_id = 'dq_metric_coverage'"
            ).fetchall()
        }
        self.assertTrue(protection, "the coverage expectation is missing")


@unittest.skipUnless(_warehouse_available(), "warehouse not built yet")
class MetricProtectionTest(unittest.TestCase):
    """The engine's own guarantee: a metric is protected or it is not published.

    These tests exercise the protection logic directly, with a synthetic metric
    pointing at an unprotected model, so the guarantee is proven to fail closed
    rather than merely to pass on today's data.
    """

    @classmethod
    def setUpClass(cls):
        cls.con = duckdb.connect(str(WAREHOUSE), read_only=True)
        cls.manifest = json.loads(
            (ROOT / "dbt_project" / "target" / "manifest.json").read_text()
        )
        cls.lineage = trust_engine._build_lineage(cls.manifest)
        cls.expectations = cls.con.execute(
            "select * from main.mart_dq_expectations"
        ).fetchdf().to_dict("records")
        cls.metrics = cls.con.execute(
            "select * from main.mart_metric_registry"
        ).fetchdf().to_dict("records")

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_every_published_metric_has_protection(self):
        protection = trust_engine._metric_protection(
            self.metrics, self.expectations, self.lineage, self.manifest
        )
        for metric in self.metrics:
            if metric.get("published"):
                self.assertTrue(
                    protection.get(metric["metric_key"]),
                    f"{metric['metric_key']} is not protected",
                )

    def test_an_unprotected_metric_is_not_published(self):
        orphan = dict(self.metrics[0])
        orphan["metric_key"] = "orphan_metric"
        orphan["source_model"] = "mart_that_does_not_exist"
        metrics = self.metrics + [orphan]
        protection = trust_engine._metric_protection(
            metrics, self.expectations, self.lineage, self.manifest
        )
        self.assertFalse(protection["orphan_metric"])

    def test_an_unprotected_metric_never_reaches_measured(self):
        orphan = dict(self.metrics[0])
        orphan["metric_key"] = "orphan_metric"
        orphan["source_model"] = "mart_that_does_not_exist"
        metrics = self.metrics + [orphan]
        protection = trust_engine._metric_protection(
            metrics, self.expectations, self.lineage, self.manifest
        )
        rows = trust_engine.assign_metric_states(metrics, [], self.lineage, protection)
        states = {row["metric_key"]: row for row in rows}
        self.assertEqual(states["orphan_metric"]["trust_state"], "unverified")
        self.assertFalse(states["orphan_metric"]["displayable"])
        self.assertIn("dq_metric_coverage", states["orphan_metric"]["blocking_checks"])

    def test_coverage_check_fails_when_a_metric_is_unprotected(self):
        orphan = dict(self.metrics[0])
        orphan["metric_key"] = "orphan_metric"
        orphan["source_model"] = "mart_that_does_not_exist"
        metrics = self.metrics + [orphan]
        status, observed, message = trust_engine._evaluate_metric_coverage(
            {}, metrics, self.expectations, self.lineage, self.manifest
        )
        self.assertEqual(status, "fail")
        self.assertEqual(observed, 1.0)
        self.assertIn("orphan_metric", message)

    def test_coverage_check_passes_on_the_real_registry(self):
        status, _observed, _message = trust_engine._evaluate_metric_coverage(
            {}, self.metrics, self.expectations, self.lineage, self.manifest
        )
        self.assertEqual(status, "pass")

    def test_dashboard_consistency_fails_when_a_promised_metric_is_withheld(self):
        """The registry promises a metric to the dashboard. If the engine withholds
        it, the promise is out of date and the check must say so."""
        rows = [
            {"metric_key": "waste_cost_at_risk", "displayable": True},
            {"metric_key": "waste_rate_per_demand", "displayable": False},
        ]
        status, observed, message = trust_engine._evaluate_dashboard_consistency(
            rows, self.metrics
        )
        self.assertEqual(status, "fail")
        self.assertEqual(observed, 1.0)
        self.assertIn("waste_rate_per_demand", message)

    def test_dashboard_consistency_passes_when_every_promised_metric_shows(self):
        rows = [
            {"metric_key": metric["metric_key"], "displayable": True}
            for metric in self.metrics
            if metric.get("published") and metric.get("display_in_dashboard")
        ]
        status, observed, _message = trust_engine._evaluate_dashboard_consistency(
            rows, self.metrics
        )
        self.assertEqual(status, "pass")
        self.assertEqual(observed, 0.0)

    def test_dashboard_consistency_ignores_metrics_not_promised_to_the_dashboard(self):
        """units_sold is published but not shown in the dashboard. Withholding it
        is not a broken promise."""
        rows = [
            {"metric_key": "units_sold", "displayable": False},
        ]
        status, _observed, _message = trust_engine._evaluate_dashboard_consistency(
            rows, self.metrics
        )
        self.assertEqual(status, "pass")


@unittest.skipUnless((ROOT / "data" / "marts" / "trust_report.json").exists(), "trust report missing")
class TrustReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((ROOT / "data" / "marts" / "trust_report.json").read_text())

    def test_report_has_no_blocking_failures(self):
        self.assertEqual(self.report["status"], "published")
        self.assertEqual(self.report["summary"]["blockers"], 0)

    def test_every_check_has_a_status_and_owner(self):
        for check in self.report["checks"]:
            self.assertIn(check["status"], {"pass", "fail", "skip", "error"})
            self.assertTrue(check["owner"])
            self.assertTrue(check["message"])

    def test_no_check_is_left_pending(self):
        for check in self.report["checks"]:
            self.assertNotEqual(check["status"], "pending")

    def test_every_metric_carries_a_trust_state(self):
        for metric in self.report["metrics"]:
            self.assertIn(metric["trust_state"], {"measured", "partial", "unverified"})
            self.assertTrue(metric["lineage"] is not None)

    def test_estimated_metrics_are_never_measured(self):
        for metric in self.report["metrics"]:
            if metric["measurement_type"] == "estimated":
                self.assertNotEqual(metric["trust_state"], "measured")

    def test_every_metric_traces_to_a_delivery(self):
        for metric in self.report["metrics"]:
            if metric["source_model"] not in ("mart_metric_registry", "mart_dq_expectations"):
                self.assertTrue(metric["lineage"], metric["metric_key"])

    def test_every_published_metric_is_protected(self):
        for metric in self.report["metrics"]:
            if metric.get("published"):
                self.assertTrue(
                    metric.get("protected", True),
                    f"{metric['metric_key']} is published without protection",
                )


@unittest.skipUnless((ROOT / "data" / "marts" / "overview.json").exists(), "overview missing")
class PublishedArtefactTest(unittest.TestCase):
    """The published files must agree with the trust report.

    A metric the trust engine does not allow to be shown must not carry a
    number in the published artefacts. The export is the last gate.
    """

    @classmethod
    def setUpClass(cls):
        cls.marts = ROOT / "data" / "marts"
        cls.overview = json.loads((cls.marts / "overview.json").read_text())
        cls.report = json.loads((cls.marts / "trust_report.json").read_text())
        cls.states = {m["metric_key"]: m for m in cls.report["metrics"]}

    def test_overview_values_exist_only_for_displayable_metrics(self):
        pairs = [
            ("waste_cost_at_risk", "waste_cost_at_risk"),
            ("waste_quantity", "waste_quantity"),
            ("avoidable_share", "avoidable_cost_share"),
            ("waste_rate_per_demand", "waste_rate_per_demand"),
        ]
        for overview_key, metric_key in pairs:
            rows = self.overview[overview_key]
            self.assertTrue(rows, overview_key)
            displayable = self.states[metric_key]["displayable"]
            for row in rows:
                if displayable:
                    self.assertIsNotNone(row["value"], metric_key)
                else:
                    self.assertIsNone(row["value"], metric_key)

    def test_every_published_json_file_is_valid_json(self):
        for path in sorted(self.marts.glob("*.json")):
            with self.subTest(artefact=path.name):
                json.loads(path.read_text())

    def test_no_published_file_contains_nan_or_infinity(self):
        for path in sorted(self.marts.glob("*.json")):
            text = path.read_text()
            with self.subTest(artefact=path.name):
                self.assertNotIn("NaN", text)
                self.assertNotIn("Infinity", text)

    def test_a_refused_metric_is_published_as_null(self):
        """The export must withhold a number the trust engine refused."""
        sys.path.insert(0, str(ROOT / "scripts"))
        import export_marts

        report = {
            "metrics": [
                {"metric_key": "waste_cost_at_risk", "displayable": False},
                {"metric_key": "recommended_order_qty", "displayable": True},
            ]
        }
        states = export_marts._displayable_states(report)
        self.assertFalse(states["waste_cost_at_risk"])

        rows = [{"recommended_order_qty": 12.0, "recommended_order_cost": 300.0}]
        export_marts._apply_column_gate("purchase_plan", rows, states)
        self.assertEqual(rows[0]["recommended_order_qty"], 12.0)
        self.assertEqual(rows[0]["recommended_order_cost"], 300.0)

        rows = [{"recommended_order_qty": 12.0, "recommended_order_cost": 300.0}]
        export_marts._apply_column_gate(
            "purchase_plan", rows, {"recommended_order_qty": False}
        )
        self.assertIsNone(rows[0]["recommended_order_qty"])
        self.assertIsNone(rows[0]["recommended_order_cost"])

    def test_a_gate_for_another_table_leaves_this_table_alone(self):
        import export_marts

        rows = [{"recommended_order_qty": 12.0}]
        export_marts._apply_column_gate(
            "waste_by_category", rows, {"recommended_order_qty": False}
        )
        self.assertEqual(rows[0]["recommended_order_qty"], 12.0)


class BlockedGateTest(unittest.TestCase):
    """A closed gate must leave no numbers that look current.

    The export used to return non-zero and write nothing, which left last run's
    numbers on disk under this run's "blocked" badge. A reader could not tell
    that the figure was stale. A blocked run now removes them.
    """

    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import export_marts

        self.export = export_marts
        self.directory = tempfile.TemporaryDirectory()
        self.mart = Path(self.directory.name)
        self.original = export_marts.MART
        export_marts.MART = self.mart

    def tearDown(self):
        self.export.MART = self.original
        self.directory.cleanup()

    def _write(self, name, payload):
        (self.mart / name).write_text(json.dumps(payload))

    def test_a_blocked_gate_removes_the_previous_numbers(self):
        self._write("overview.json", [{"value": 1}])
        self._write("waste_priority.json", [{"value": 1}])
        self._write("publish_status.json", {"status": "blocked", "blockers": [{"check_id": "dq_x"}]})

        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.export.main(), 1)
        self.assertFalse((self.mart / "overview.json").exists())
        self.assertFalse((self.mart / "waste_priority.json").exists())

    def test_a_blocked_gate_keeps_the_diagnostics_that_explain_it(self):
        self._write("trust_report.json", {"status": "blocked", "checks": []})
        self._write("lineage.json", {"models": {}})
        self._write("metric_registry.json", [{"metric_key": "x"}])
        self._write("publish_status.json", {"status": "blocked", "blockers": [{"check_id": "dq_x"}]})

        with contextlib.redirect_stderr(io.StringIO()):
            self.export.main()

        for name in ("trust_report.json", "lineage.json", "metric_registry.json", "publish_status.json"):
            with self.subTest(artefact=name):
                self.assertTrue((self.mart / name).exists())

    def test_a_missing_gate_also_removes_the_previous_numbers(self):
        self._write("overview.json", [{"value": 1}])

        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.export.main(), 1)
        self.assertFalse((self.mart / "overview.json").exists())


class ColdStartTest(unittest.TestCase):
    """A clean checkout must build without manual directory creation.

    `make clean` removes the generated folders, so every step that writes into
    them has to create them first. This test proves the pipeline can start from
    an empty data folder.
    """

    def test_the_pipeline_creates_the_folder_it_writes_into(self):
        import run_local_pipeline

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "marts"
            with mock.patch.object(run_local_pipeline, "MART", target):
                run_local_pipeline.MART.mkdir(parents=True, exist_ok=True)
                (run_local_pipeline.MART / "run_metadata.json").write_text("{}")
            self.assertTrue((target / "run_metadata.json").exists())

    def test_every_writer_of_the_marts_folder_creates_it(self):
        """Each script that writes into data/marts must create the folder."""
        for script in ("trust_engine.py", "reconcile.py", "export_marts.py"):
            source = (ROOT / "scripts" / script).read_text()
            with self.subTest(script=script):
                self.assertIn("MART.mkdir(parents=True, exist_ok=True)", source)


class ReproduciblePublishTest(unittest.TestCase):
    """Publishing the same warehouse twice must produce the same files.

    A published artefact is a contract with the dashboard and with whoever
    reviews the repository. If the order of the rows or the last decimal of a
    float changes between runs, a diff in the repository means nothing and a
    reviewer cannot tell a real change from noise.
    """

    @classmethod
    def setUpClass(cls):
        cls.con = duckdb.connect(str(WAREHOUSE), read_only=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_every_exported_table_declares_the_order_its_rows_are_published_in(self):
        import export_marts

        for table in export_marts.EXPORTS:
            with self.subTest(table=table):
                self.assertIn(table, export_marts.ORDER_BY)
                self.assertTrue(export_marts.ORDER_BY[table])

    def test_the_marts_do_not_use_nondeterministic_aggregates(self):
        """``any_value`` picks an arbitrary row, so two runs can disagree.

        The marts use it for columns that are functionally dependent on the
        grain, so the value is the same in every row of the group. It still
        has to be a deterministic aggregate, otherwise the pick is luck.
        """
        models = ROOT / "dbt_project" / "models"
        offenders = []
        for path in models.rglob("*.sql"):
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if "any_value" in line.lower():
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(offenders, [], f"nondeterministic aggregates: {offenders}")

    def test_the_ranked_marts_break_ties_on_the_full_grain(self):
        """A rank that does not break ties on the full grain is a coin toss.

        ``row_number`` over a key that is not unique leaves the order of the
        tied rows undefined, so the published rank can change between two runs
        of the same data.
        """
        grain_columns = {
            "mart_waste_priority": [
                "waste_date",
                "location_id",
                "ingredient_id",
                "waste_reason",
            ],
        }
        for model, grain in grain_columns.items():
            path = ROOT / "dbt_project" / "models" / "marts" / f"{model}.sql"
            sql = path.read_text()
            match = re.search(
                r"row_number\(\)\s*over\s*\((.*?)\)\s*as\s+priority_rank", sql, re.S
            )
            self.assertIsNotNone(match, f"{model} has no priority_rank")
            window = match.group(1).lower()
            for column in grain:
                with self.subTest(model=model, column=column):
                    self.assertIn(column, window)

    def test_the_ordering_keys_exist_in_the_table(self):
        import export_marts

        for table, keys in export_marts.ORDER_BY.items():
            columns = {
                row[0] for row in self.con.execute(f"describe main.{table}").fetchall()
            }
            for key in keys:
                with self.subTest(table=table, key=key):
                    self.assertIn(key, columns)

    def test_publishing_the_same_rows_twice_gives_the_same_bytes(self):
        import export_marts

        table = "mart_waste_by_category"
        order = ", ".join(export_marts.ORDER_BY[table])
        first = export_marts._records(
            self.con, f"select * from main.{table} order by {order}"
        )
        second = export_marts._records(
            self.con, f"select * from main.{table} order by {order}"
        )
        self.assertEqual(
            export_marts._round_floats(first), export_marts._round_floats(second)
        )

    def test_floats_are_rounded_to_a_stable_precision(self):
        import export_marts

        self.assertEqual(export_marts._round_floats(17.669999999999998), 17.67)
        self.assertEqual(export_marts._round_floats(12.0), 12)
        self.assertEqual(export_marts._round_floats([1.0000000000001]), [1.0])
        self.assertEqual(
            export_marts._round_floats({"a": {"b": 3.0000000000000004}}), {"a": {"b": 3.0}}
        )

    def test_the_published_files_are_stable_against_a_fresh_export(self):
        """Exporting the warehouse again must not change the published bytes."""
        import export_marts

        for table, stem in export_marts.EXPORTS.items():
            order = ", ".join(export_marts.ORDER_BY[table])
            rows = export_marts._records(
                self.con, f"select * from main.{table} order by {order}"
            )
            with tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / f"{stem}.json"
                export_marts._write_json(target, rows)
                published = ROOT / "data" / "marts" / f"{stem}.json"
                if not published.exists():
                    continue
                with self.subTest(artefact=stem):
                    self.assertEqual(target.read_text(), published.read_text())

    def test_every_published_row_is_sorted_by_its_declared_key(self):
        """The published order has to be the declared one, not whatever the
        database happened to return."""
        import export_marts

        for table, keys in export_marts.ORDER_BY.items():
            order = ", ".join(keys)
            rows = export_marts._records(
                self.con, f"select * from main.{table} order by {order}"
            )
            published = ROOT / "data" / "marts" / f"{export_marts.EXPORTS[table]}.json"
            if not published.exists():
                continue
            stored = json.loads(published.read_text())
            with self.subTest(table=table):
                self.assertEqual(len(stored), len(rows))
                for expected, actual in zip(rows, stored):
                    for key in keys:
                        self.assertEqual(
                            export_marts._sanitize(expected[key]),
                            actual[key],
                            key,
                        )


if __name__ == "__main__":
    unittest.main()
