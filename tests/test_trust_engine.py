"""Trust engine tests: the rules that decide what may be shown."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import trust_engine  # noqa: E402


def _check(check_id, severity="blocker", status="pass", target="mart_waste_priority"):
    return {
        "check_id": check_id,
        "target_model": target,
        "severity": severity,
        "status": status,
        "message": "",
        "remediation": "",
    }


def _metric(key="waste_cost_at_risk", model="mart_waste_priority", measurement="derived"):
    return {
        "metric_key": key,
        "metric_name": key,
        "source_model": model,
        "measurement_type": measurement,
        "published": True,
        "owner": "ops analytics",
        "caveat": "",
        "definition": "",
        "trust_states_allowed": ["measured", "partial"],
        "unit": "NOK",
    }


LINEAGE = {
    "models": {
        "mart_waste_priority": {
            "depends_on_models": ["mart_waste_opportunity"],
            "depends_on_sources": [],
        },
        "mart_waste_opportunity": {
            "depends_on_models": ["fct_waste_events"],
            "depends_on_sources": [],
        },
        "fct_waste_events": {
            "depends_on_models": [],
            "depends_on_sources": ["waste_events", "ingredients", "locations"],
        },
    },
    "sources": ["waste_events", "ingredients", "locations"],
}


class TrustStateTest(unittest.TestCase):
    def test_all_checks_pass_means_measured(self):
        states = trust_engine.assign_metric_states(
            [_metric()], [_check("dq_ok")], LINEAGE
        )
        self.assertEqual(states[0]["trust_state"], "measured")
        self.assertTrue(states[0]["displayable"])

    def test_blocking_failure_makes_the_metric_unverified(self):
        states = trust_engine.assign_metric_states(
            [_metric()], [_check("dq_broken", status="fail")], LINEAGE
        )
        self.assertEqual(states[0]["trust_state"], "unverified")
        self.assertFalse(states[0]["displayable"])
        self.assertEqual(states[0]["blocking_checks"], ["dq_broken"])

    def test_warning_failure_downgrades_to_partial(self):
        states = trust_engine.assign_metric_states(
            [_metric()], [_check("dq_warn", severity="warning", status="fail")], LINEAGE
        )
        self.assertEqual(states[0]["trust_state"], "partial")
        self.assertTrue(states[0]["displayable"])

    def test_estimates_are_never_measured(self):
        states = trust_engine.assign_metric_states(
            [_metric(key="expected_attendance", model="fct_demand_events", measurement="estimated")],
            [_check("dq_ok", target="fct_demand_events")],
            LINEAGE,
        )
        self.assertEqual(states[0]["trust_state"], "partial")

    def test_global_checks_apply_to_every_metric(self):
        states = trust_engine.assign_metric_states(
            [_metric()], [_check("dq_fresh", target="silver", status="fail")], LINEAGE
        )
        self.assertEqual(states[0]["trust_state"], "unverified")

    def test_lineage_walks_up_to_the_delivery(self):
        states = trust_engine.assign_metric_states([_metric()], [_check("dq_ok")], LINEAGE)
        self.assertEqual(
            states[0]["lineage"], ["ingredients", "locations", "waste_events"]
        )

    def test_measured_metric_may_be_shown_when_unverified(self):
        """A source-recorded quantity is still true, it just lacks context."""
        metric = {
            **_metric(key="waste_quantity", model="fct_waste_events", measurement="measured"),
            "trust_states_allowed": ["measured", "partial", "unverified"],
        }
        states = trust_engine.assign_metric_states(
            [metric], [_check("dq_broken", status="fail", target="fct_waste_events")], LINEAGE
        )
        self.assertEqual(states[0]["trust_state"], "unverified")
        self.assertTrue(states[0]["displayable"])
        self.assertFalse(states[0]["trusted"])

    def test_metric_outside_allowed_states_is_not_displayable(self):
        metric = {**_metric(), "trust_states_allowed": ["measured"]}
        states = trust_engine.assign_metric_states(
            [metric], [_check("dq_warn", severity="warning", status="fail")], LINEAGE
        )
        self.assertEqual(states[0]["trust_state"], "partial")
        self.assertFalse(states[0]["displayable"])


class ComparisonTest(unittest.TestCase):
    def test_operators(self):
        self.assertTrue(trust_engine._check_status("eq", 0.0, 0.0))
        self.assertTrue(trust_engine._check_status("lte", 1.0, 2.0))
        self.assertTrue(trust_engine._check_status("gte", 2.0, 2.0))
        self.assertFalse(trust_engine._check_status("gte", 1.0, 2.0))

    def test_unknown_operator_raises(self):
        with self.assertRaises(ValueError):
            trust_engine._check_status("approximately", 1.0, 1.0)


class FreshnessDeterminismTest(unittest.TestCase):
    """The oldest source must be the same from one run to the next.

    Every source of a delivery is ingested in the same run, so their ages are
    equal. The check then has to break the tie by name, or the published
    message would depend on the order the sources happened to be read in.
    """

    def _connection(self, age_hours):
        import duckdb
        from datetime import datetime, timedelta, timezone

        ingested_at = datetime.now(timezone.utc) - timedelta(hours=age_hours)
        con = duckdb.connect()
        con.execute("create schema silver")
        for table in trust_engine.SOURCE_TABLES:
            con.execute(f'create table silver."{table}" (_ingested_at timestamp)')
            con.execute(
                f"insert into silver.\"{table}\" values (timestamp '{ingested_at.isoformat()}')"
            )
        return con

    def test_equal_ages_break_the_tie_by_name(self):
        con = self._connection(1)
        try:
            status, observed, message = trust_engine._evaluate_source_freshness(
                con, {"threshold": 3}
            )
        finally:
            con.close()
        self.assertEqual(status, "pass")
        self.assertIn(f"oldest silver source {min(trust_engine.SOURCE_TABLES)}", message)

    def test_an_old_source_fails_the_check(self):
        con = self._connection(24 * 10)
        try:
            status, observed, message = trust_engine._evaluate_source_freshness(
                con, {"threshold": 3}
            )
        finally:
            con.close()
        self.assertEqual(status, "fail")
        self.assertGreater(observed, 3)


if __name__ == "__main__":
    unittest.main()
