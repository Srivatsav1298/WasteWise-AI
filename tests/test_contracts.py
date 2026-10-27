"""Contract tests: the rules that every delivery must satisfy."""
import unittest

from ingestion import contracts


VALID_SALES = {
    "sale_id": "S-1",
    "sale_date": "2026-09-01",
    "location_id": "oslo_central",
    "product_id": "salmon_open",
    "units_sold": "12",
}


class ContractValidationTest(unittest.TestCase):
    def test_valid_row_passes(self):
        self.assertEqual(contracts.validate_rows("sales.csv", [dict(VALID_SALES)]), [])

    def test_missing_required_column_is_reported(self):
        row = dict(VALID_SALES)
        del row["product_id"]
        errors = contracts.validate_rows("sales.csv", [row])
        self.assertTrue(errors)
        self.assertEqual(errors[0]["code"], "missing_column")
        self.assertEqual(errors[0]["column"], "product_id")
        self.assertEqual(errors[0]["severity"], "blocker")

    def test_null_in_required_column_is_reported(self):
        row = {**VALID_SALES, "units_sold": None}
        errors = contracts.validate_rows("sales.csv", [row])
        self.assertTrue(any(error["code"] == "null_value" for error in errors))

    def test_non_numeric_value_is_reported(self):
        row = {**VALID_SALES, "units_sold": "many"}
        errors = contracts.validate_rows("sales.csv", [row])
        self.assertTrue(any(error["code"] == "invalid_type" for error in errors))

    def test_negative_value_violates_minimum(self):
        row = {**VALID_SALES, "units_sold": "-3"}
        errors = contracts.validate_rows("sales.csv", [row])
        self.assertTrue(any(error["code"] == "negative_value" for error in errors))

    def test_enum_violation_is_reported(self):
        row = {
            "waste_id": "W-1",
            "location_id": "oslo_central",
            "waste_date": "2026-09-01",
            "ingredient_id": "salmon",
            "quantity": "1.5",
            "reason": "sunshine",
        }
        errors = contracts.validate_rows("waste_events.csv", [row])
        self.assertTrue(any(error["code"] == "enum_violation" for error in errors))

    def test_error_carries_row_and_location(self):
        row = {**VALID_SALES, "units_sold": "many"}
        errors = contracts.validate_rows("sales.csv", [row])
        self.assertEqual(errors[0]["row"], 2)
        self.assertIn("message", errors[0])


class ContractNormalizationTest(unittest.TestCase):
    def test_numeric_and_date_are_typed(self):
        row = contracts.normalize_row("sales.csv", dict(VALID_SALES))
        self.assertEqual(row["units_sold"], 12)
        self.assertEqual(str(row["sale_date"]), "2026-09-01")

    def test_categorical_values_are_lowercased(self):
        row = contracts.normalize_row(
            "waste_events.csv",
            {
                "waste_id": "W-1",
                "location_id": "OSLO_CENTRAL",
                "waste_date": "2026-09-01",
                "ingredient_id": "salmon",
                "quantity": "1.5",
                "reason": "Spoilage",
            },
        )
        self.assertEqual(row["reason"], "spoilage")
        self.assertEqual(row["location_id"], "oslo_central")

    def test_missing_optional_value_stays_none(self):
        row = contracts.normalize_row("events.csv", {
            "event_id": "E-1",
            "event_name": "Test",
            "event_date": "2026-09-01",
            "event_type": "festival",
            "venue": "Oslo",
            "city": "oslo",
            "expected_attendance": "",
        })
        self.assertIsNone(row["expected_attendance"])


class ContractMetadataTest(unittest.TestCase):
    def test_every_source_declares_grain_and_key(self):
        for name, spec in contracts.SOURCES.items():
            self.assertTrue(spec["grain"], name)
            self.assertTrue(spec["natural_key"], name)
            self.assertTrue(spec["columns"], name)

    def test_contract_version_is_exposed(self):
        self.assertRegex(contracts.CONTRACT_VERSION, r"^\d+\.\d+\.\d+$")

    def test_unknown_source_raises(self):
        with self.assertRaises(KeyError):
            contracts.get_contract("nope.csv")


if __name__ == "__main__":
    unittest.main()
