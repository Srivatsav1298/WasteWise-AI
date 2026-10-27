"""The reproducibility promise, tested on the comparison itself.

Two clean runs must publish the same numbers. The artefacts still carry the
identity of the run and the wall clock, so the comparison ignores those parts
and nothing else.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import check_reproducible


class ReproducibilityComparisonTest(unittest.TestCase):
    def setUp(self):
        self.first = Path(tempfile.mkdtemp(prefix="wastewise-first-"))
        self.second = Path(tempfile.mkdtemp(prefix="wastewise-second-"))

    def tearDown(self):
        shutil.rmtree(self.first, ignore_errors=True)
        shutil.rmtree(self.second, ignore_errors=True)

    def _write(self, directory, name, payload):
        (directory / name).write_text(json.dumps(payload, indent=2))

    def _both(self, payload, name="waste_cost_at_risk.json"):
        self._write(self.first, name, payload)
        self._write(self.second, name, payload)

    def test_two_identical_runs_do_not_drift(self):
        self._both({"metric_key": "waste_cost_at_risk", "value": 1234.56})
        self.assertEqual(check_reproducible.drifted(self.first, self.second), [])

    def test_the_run_id_and_the_timestamps_may_move(self):
        self._both(
            {
                "run_id": "20260101T000000Z-aaaaaa",
                "generated_at": "2026-01-01T00:00:00+00:00",
                "value": 10,
            }
        )
        self._write(
            self.second,
            "waste_cost_at_risk.json",
            {
                "run_id": "20260101T010203Z-bbbbbb",
                "generated_at": "2026-01-01T01:02:03+00:00",
                "value": 10,
            },
        )
        self.assertEqual(check_reproducible.drifted(self.first, self.second), [])

    def test_the_bronze_snapshot_path_may_move(self):
        self._both({"bronze_snapshot": "data/bronze/sales.csv/20260101T000000Z-aaaaaa.parquet", "value": 10})
        self._write(
            self.second,
            "waste_cost_at_risk.json",
            {"bronze_snapshot": "data/bronze/sales.csv/20260101T010203Z-bbbbbb.parquet", "value": 10},
        )
        self.assertEqual(check_reproducible.drifted(self.first, self.second), [])

    def test_the_observed_value_may_move(self):
        self._both({"observed": 5, "value": 10})
        self._write(self.second, "waste_cost_at_risk.json", {"observed": 6, "value": 10})
        self.assertEqual(check_reproducible.drifted(self.first, self.second), [])

    def test_the_age_in_a_message_may_move_but_the_words_may_not(self):
        self._both({"message": "oldest silver source events is 0.08 days old"})
        self._write(
            self.second,
            "waste_cost_at_risk.json",
            {"message": "oldest silver source events is 0.91 days old"},
        )
        self.assertEqual(check_reproducible.drifted(self.first, self.second), [])

        self._write(
            self.second,
            "waste_cost_at_risk.json",
            {"message": "newest silver source events is 0.91 days old"},
        )
        self.assertEqual(
            check_reproducible.drifted(self.first, self.second),
            ["waste_cost_at_risk.json"],
        )

    def test_a_changed_number_drifts(self):
        self._both({"value": 10})
        self._write(self.second, "waste_cost_at_risk.json", {"value": 11})
        self.assertEqual(
            check_reproducible.drifted(self.first, self.second),
            ["waste_cost_at_risk.json"],
        )

    def test_a_missing_artefact_drifts(self):
        self._write(self.first, "waste_cost_at_risk.json", {"value": 10})
        self._write(self.second, "other.json", {"value": 10})
        self.assertEqual(
            check_reproducible.drifted(self.first, self.second),
            ["other.json"],
        )

    def test_the_script_fails_loudly_on_drift(self):
        self._both({"value": 10})
        self._write(self.second, "waste_cost_at_risk.json", {"value": 11})
        self.assertEqual(check_reproducible.main([str(self.first), str(self.second)]), 1)

    def test_the_script_passes_on_identical_runs(self):
        self._both({"value": 10})
        self.assertEqual(check_reproducible.main([str(self.first), str(self.second)]), 0)


if __name__ == "__main__":
    unittest.main()
