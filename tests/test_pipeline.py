"""End to end pipeline test: the published artefacts must exist and agree."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PublishedArtefactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            [sys.executable, "scripts/run_end_to_end.py", "--no-delivery"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AssertionError(f"pipeline failed: {result.stdout}\n{result.stderr}")

    def _json(self, name):
        return json.loads((ROOT / "data" / "marts" / name).read_text())

    def test_legacy_clean_exports_exist(self):
        self.assertTrue((ROOT / "data" / "clean" / "sales.csv").exists())

    def test_run_metadata_records_success(self):
        metadata = json.loads((ROOT / "data" / "marts" / "run_metadata.json").read_text())
        self.assertEqual(metadata["status"], "success")

    def test_waste_by_reason_contains_known_reasons(self):
        rows = json.loads((ROOT / "data" / "marts" / "waste_by_reason.json").read_text())
        reasons = {row["waste_reason"] for row in rows}
        self.assertIn("spoilage", reasons)
        self.assertIn("overproduction", reasons)

    def test_publish_status_is_published(self):
        status = self._json("publish_status.json")
        self.assertEqual(status["status"], "published")
        self.assertEqual(status["blockers"], [])

    def test_trust_report_covers_every_metric(self):
        report = self._json("trust_report.json")
        registry = self._json("metric_registry.json")
        self.assertEqual(len(report["metrics"]), len(registry))
        self.assertEqual(report["summary"]["blockers"], 0)

    def test_overview_is_published_for_the_dashboard(self):
        overview = self._json("overview.json")
        for key in (
            "waste_cost_at_risk",
            "waste_quantity",
            "avoidable_share",
            "locations",
            "top_ingredients",
            "daily_trend",
        ):
            self.assertIn(key, overview)

    def test_reconciliation_reports_every_source(self):
        report = self._json("reconciliation.json")
        for source in (
            "sales.csv",
            "inventory_snapshots.csv",
            "waste_events.csv",
            "events.csv",
            "products.csv",
            "ingredients.csv",
            "locations.csv",
        ):
            self.assertIn(source, report["sources"])
            entry = report["sources"][source]
            self.assertEqual(
                entry["rows_published"],
                entry["rows_delivered"] - entry["rows_rejected"] - entry["duplicates_removed"],
                source,
            )

    def test_reconciliation_totals_match_the_source_ledger(self):
        report = self._json("reconciliation.json")
        totals = report["totals"]
        sources = report["sources"].values()
        self.assertEqual(totals["rows_in"], sum(row["rows_delivered"] for row in sources))
        self.assertEqual(totals["rows_out"], sum(row["rows_published"] for row in sources))
        self.assertEqual(totals["rows_rejected"], sum(row["rows_rejected"] for row in sources))
        self.assertEqual(totals["duplicates_removed"], sum(row["duplicates_removed"] for row in sources))
        self.assertGreater(totals["rows_in"], 0)
        self.assertGreater(totals["rows_out"], 0)

    def test_run_metadata_totals_match_the_reconciliation_ledger(self):
        metadata = self._json("run_metadata.json")
        totals = self._json("reconciliation.json")["totals"]
        self.assertEqual(metadata["rows_in"], totals["rows_in"])
        self.assertEqual(metadata["rows_out"], totals["rows_out"])

    def test_lineage_is_exported(self):
        lineage = self._json("lineage.json")
        self.assertIn("models", lineage)
        self.assertIn("waste_events", lineage["sources"])


if __name__ == "__main__":
    unittest.main()


class BlockedPipelineTest(unittest.TestCase):
    """A refused trust run must still withdraw the published numbers.

    The pipeline stops at the first failing step, but when the trust engine
    closes the gate the publish step still has to run: that is what removes the
    stale figures. Without it a blocked run leaves last run's numbers on disk.
    """

    def test_a_refused_trust_run_still_runs_the_publish_step(self):
        from unittest import mock

        import orchestration.pipeline as pipeline

        calls = []

        def fake_run(label, command, cwd=None):
            calls.append(label)
            if label == "trust engine":
                raise SystemExit("blocked")

        with mock.patch.object(pipeline, "_run", side_effect=fake_run):
            with self.assertRaises(SystemExit):
                pipeline.run(include_delivery=False)

        self.assertIn("publish", calls)
        self.assertEqual(calls[-1], "publish")

    def test_a_delivery_failure_skips_the_rest_of_the_run(self):
        from unittest import mock

        import orchestration.pipeline as pipeline

        calls = []

        def fake_run(label, command, cwd=None):
            calls.append(label)
            if label == "bronze+silver":
                raise SystemExit("invalid delivery")

        with mock.patch.object(pipeline, "_run", side_effect=fake_run):
            with self.assertRaises(SystemExit):
                pipeline.run(include_delivery=False)

        self.assertEqual(calls, ["bronze+silver"])
