"""Silver layer tests: validation, deduplication, quarantine and publication."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import duckdb

from ingestion import bronze, contracts, silver

ROOT = Path(__file__).resolve().parents[1]


class SilverProcessingTest(unittest.TestCase):
    """Runs the silver layer against a controlled delivery in a temp directory."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wastewise-silver-"))
        cls.raw = cls.tmp / "raw"
        cls.raw.mkdir(parents=True)

        header = "sale_id,sale_date,location_id,product_id,units_sold\n"
        rows = [
            "S-1,2026-09-01,oslo_central,salmon_open,10",
            "S-2,2026-09-01,oslo_central,berry_bowl,4",
            "S-1,2026-09-01,oslo_central,salmon_open,12",  # late correction
            "S-3,2026-09-01,oslo_central,salmon_open,-5",  # invalid: negative
        ]
        (cls.raw / "sales.csv").write_text(header + "\n".join(rows) + "\n")

        cls.original_raw = silver.RAW
        cls.original_silver = silver.SILVER
        cls.original_rejects = silver.REJECTS
        cls.original_quarantine = silver.QUARANTINE
        cls.original_warehouse = silver.WAREHOUSE
        cls.original_bronze = bronze.BRONZE
        cls.original_bronze_manifests = bronze.MANIFESTS
        silver.RAW = cls.raw
        silver.SILVER = cls.tmp / "silver"
        silver.REJECTS = cls.tmp / "silver" / "rejects"
        silver.QUARANTINE = cls.tmp / "quarantine"
        silver.WAREHOUSE = cls.tmp / "warehouse.duckdb"
        bronze.BRONZE = cls.tmp / "bronze"
        bronze.MANIFESTS = cls.tmp / "bronze" / "_manifests"

        bronze.ingest_source("sales.csv", cls.raw / "sales.csv", "test-run")
        cls.manifest = silver.process_source("sales.csv")

    @classmethod
    def tearDownClass(cls):
        silver.RAW = cls.original_raw
        silver.SILVER = cls.original_silver
        silver.REJECTS = cls.original_rejects
        silver.QUARANTINE = cls.original_quarantine
        silver.WAREHOUSE = cls.original_warehouse
        bronze.BRONZE = cls.original_bronze
        bronze.MANIFESTS = cls.original_bronze_manifests
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_manifest_counts_delivered_rows(self):
        self.assertEqual(self.manifest["rows_in"], 4)

    def test_invalid_row_is_quarantined(self):
        self.assertEqual(self.manifest["rows_rejected"], 1)
        quarantine = json.loads((silver.QUARANTINE / "sales.errors.json").read_text())
        self.assertEqual(quarantine["rejected_rows"], 1)
        self.assertTrue(quarantine["errors"][0]["errors"])

    def test_duplicate_is_removed_and_last_wins(self):
        self.assertEqual(self.manifest["duplicates_removed"], 1)
        self.assertEqual(self.manifest["rows_out"], 2)
        con = duckdb.connect(str(silver.WAREHOUSE))
        try:
            value = con.execute(
                'select units_sold from silver.sales where sale_id = \'S-1\''
            ).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(int(value), 12)

    def test_rejects_are_written_to_disk(self):
        rejects = silver.REJECTS / "sales.parquet"
        self.assertTrue(rejects.exists())

    def test_published_table_is_registered_in_the_warehouse(self):
        con = duckdb.connect(str(silver.WAREHOUSE))
        try:
            names = {
                row[0]
                for row in con.execute(
                    "select table_name from information_schema.tables where table_schema = 'silver'"
                ).fetchall()
            }
        finally:
            con.close()
        self.assertIn("sales", names)

    def test_manifest_records_contract_version_and_grain(self):
        self.assertEqual(self.manifest["contract_version"], contracts.CONTRACT_VERSION)
        self.assertEqual(self.manifest["grain"], ["sale_id"])

    def test_row_is_valid_matches_validate_rows(self):
        row = {
            "sale_id": "S-9",
            "sale_date": "2026-09-01",
            "location_id": "oslo_central",
            "product_id": "salmon_open",
            "units_sold": "3",
        }
        self.assertTrue(contracts.row_is_valid("sales.csv", row))
        self.assertEqual(contracts.validate_rows("sales.csv", [row]), [])

        broken = {**row, "units_sold": "-1"}
        self.assertFalse(contracts.row_is_valid("sales.csv", broken))
        self.assertTrue(contracts.validate_rows("sales.csv", [broken]))


class BronzeRunTest(unittest.TestCase):
    """One delivery, one ingest timestamp.

    If every source carried its own timestamp, the freshness check would name
    a different oldest source depending on where the clock crossed a second
    boundary, and the published trust report would differ from run to run.
    """

    def test_every_source_of_a_run_shares_one_ingest_timestamp(self):
        tmp = Path(tempfile.mkdtemp(prefix="wastewise-bronze-"))
        try:
            raw = tmp / "data" / "raw"
            raw.mkdir(parents=True)
            (raw / "a.csv").write_text("id\n1\n")
            (raw / "b.csv").write_text("id\n2\n")

            original_root = bronze.ROOT
            original_bronze = bronze.BRONZE
            original_manifests = bronze.MANIFESTS
            bronze.ROOT = tmp
            bronze.BRONZE = tmp / "bronze"
            bronze.MANIFESTS = tmp / "bronze" / "_manifests"
            try:
                result = bronze.ingest_all(["a.csv", "b.csv"], "run-1")
            finally:
                bronze.ROOT = original_root
                bronze.BRONZE = original_bronze
                bronze.MANIFESTS = original_manifests

            stamps = {manifest["ingested_at"] for manifest in result["sources"]}
            self.assertEqual(len(stamps), 1)
            self.assertEqual(result["ingested_at"], stamps.pop())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
