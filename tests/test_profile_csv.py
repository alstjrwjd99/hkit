"""Behavioral regression checks for profiling and draft contract generation."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / ".agents/skills/eda/scripts/profile_csv.py"


class ProfileTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)

    def run_profile(self, text, *options, encoding="utf-8-sig", name="input.csv", success=True):
        source = self.root / name
        raw = text.encode(encoding)
        source.write_bytes(raw)
        result = subprocess.run(
            [sys.executable, "-X", "utf8", SCRIPT, source, *options],
            capture_output=True, encoding="utf-8", timeout=10,
        )
        self.assertEqual(source.read_bytes(), raw)
        if not success:
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            return result
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_types_missing_ranges_and_legacy_counts(self):
        report = self.run_profile(
            "id,amount,active,mixed\n001,0.1,true,2\n002,100000000000000000.03,false,x\n003, ,true,\nwrong\n"
        )
        self.assertEqual((report["records"], report["valid_width"], report["wrong_width"]), (4, 3, 1))
        self.assertEqual(report["columns"]["id"]["inferred_type"], "string")
        self.assertEqual(report["columns"]["active"]["inferred_type"], "boolean")
        self.assertEqual(report["columns"]["mixed"]["inferred_type"], "mixed")
        amount = report["columns"]["amount"]
        self.assertEqual(amount["numeric_range"], {"min": "0.1", "max": "100000000000000000.03"})
        self.assertEqual(amount["missing_rate"], 1 / 3)
        self.assertEqual(report["missing_in_valid_rows"]["mixed"], 1)

    def test_explicit_and_automatic_dates(self):
        report = self.run_profile(
            "iso,custom\n2024-02-29,20240229\n2025-02-29,20250229\ntext,broken\n",
            "--date", "custom=%Y%m%d",
        )
        iso = report["columns"]["iso"]["date_validation"]
        custom = report["columns"]["custom"]["date_validation"]
        self.assertEqual((iso["valid"], iso["invalid"], iso["scope"]), (1, 1, "iso_looking_values"))
        self.assertEqual((custom["valid"], custom["invalid"], custom["scope"]), (1, 2, "all_non_missing"))

    def test_composite_key_duplicates_and_missing(self):
        report = self.run_profile(
            "route,stop\nA,1\nA,2\nA,1\nB,\n", "--key", "route,stop",
        )
        key = report["keys"][0]
        self.assertEqual((key["duplicate_rows_after_first"], key["missing_rows"]), (1, 1))
        self.assertFalse(key["unique_non_missing_candidate"])
        self.assertFalse(report["columns"]["route"]["unique_non_missing_candidate"])

    def test_cp949_and_encoding_error_are_distinct(self):
        report = self.run_profile("노선,수요\n서울,10\n", "--encoding", "cp949", encoding="cp949")
        self.assertEqual(report["encoding"], "cp949")
        self.assertEqual(report["columns"]["수요"]["inferred_type"], "integer")
        failure = self.run_profile("노선,수요\n서울,10\n", encoding="cp949", success=False)
        self.assertIn("encoding error", failure.stderr)
        self.assertIn("--encoding", failure.stderr)

    def test_sampling_stops_before_malformed_following_record(self):
        report = self.run_profile('id\n1\n2\n"unterminated', "--max-rows", "2")
        self.assertEqual(report["records"], 2)
        self.assertFalse(report["complete_scan"])
        self.assertTrue(report["columns"]["id"]["unique_non_missing_candidate"])

    def test_empty_and_header_only(self):
        failure = self.run_profile("", success=False)
        self.assertIn("header", failure.stderr)
        report = self.run_profile("id,value\n")
        self.assertEqual(report["records"], 0)
        self.assertIsNone(report["columns"]["id"]["missing_rate"])
        self.assertEqual(report["columns"]["id"]["inferred_type"], "unknown")
        self.assertFalse(report["columns"]["id"]["unique_non_missing_candidate"])

    def test_invalid_header_csv_and_arguments(self):
        for content in ["id,id\n1,2\n", "id,\n1,2\n", 'id,value\n1,"unterminated']:
            with self.subTest(content=content):
                self.run_profile(content, success=False)
        for options in [
            ("--key", "missing"), ("--key", "id,id"), ("--date", "bad"),
            ("--encoding", "unknown-codec"), ("--max-rows", "0"),
        ]:
            with self.subTest(options=options):
                self.run_profile("id\n1\n", *options, success=False)

    def test_tsv_and_multiline_duplicate(self):
        report = self.run_profile('id\tvalue\n"bus\n1"\t0\n"bus\n1"\t0\n', name="input.tsv")
        self.assertEqual(report["duplicate_rows_after_first"], 1)
        self.assertEqual(report["records"], 2)

    def test_contract_draft_has_provenance_and_no_implicit_constraints(self):
        output = self.root / "data-contract.json"
        report = self.run_profile(
            "id,count\n1,1\n2,999\n", "--contract-out", str(output), "--prd-revision", "P2",
        )
        contract = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(contract["schema_version"], 1)
        self.assertEqual((contract["status"], contract["prd_revision"]), ("draft", "P2"))
        self.assertEqual(contract["constraints"], [])
        self.assertEqual(contract["observations"], report)
        self.assertEqual(contract["source"]["sha256"], hashlib.sha256((self.root / "input.csv").read_bytes()).hexdigest())
        snapshot = output.read_bytes()
        failure = self.run_profile("id,count\n1,1\n2,999\n", "--contract-out", str(output), success=False)
        self.assertIn("already exists", failure.stderr)
        self.assertEqual(output.read_bytes(), snapshot)
        self.run_profile("id\n1\n", "--contract-out", str(self.root / "input.csv"), success=False)

    def test_extreme_numeric_notation_does_not_crash(self):
        report = self.run_profile("n\n1e999999999999999999999999\nNaN\nInfinity\n")
        self.assertEqual(report["columns"]["n"]["inferred_type"], "string")
        self.assertIsNone(report["columns"]["n"]["numeric_range"])


if __name__ == "__main__":
    unittest.main()
