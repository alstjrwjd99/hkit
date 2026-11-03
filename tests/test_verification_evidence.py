"""Freshness and acceptance gates for the integrated verification record."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from examples.prd_eda_be.workflow import apply_decision


KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / ".agents/skills/check/scripts"))
from verify_evidence import snapshot, verify, write_evidence


class VerificationEvidenceTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        inputs = {}
        for role in ["prd", "contract", "data", "code", "tests"]:
            path = self.root / (role + ".txt")
            path.write_text(role + " P1", encoding="utf-8")
            inputs[role] = [path.name]
        self.context = self.root / "context.json"
        self.context.write_text(json.dumps({
            "schema_version": 1, "inputs": inputs, "required_ac": ["R1-AC1"],
        }), encoding="utf-8")
        self.log = self.root / "result.json"
        self.result = {
            "command": ["python", "test_example.py"], "returncode": 0,
            "checks": [{"id": "B01", "ac_ids": ["R1-AC1"], "status": "PASS"}],
        }
        self.save_result()
        self.evidence = self.root / "evidence.json"
        write_evidence(self.evidence, snapshot(self.context), self.log)

    def save_result(self):
        self.log.write_text(json.dumps(self.result), encoding="utf-8")

    def verdict(self):
        return verify(self.context, self.evidence)

    def recapture_result(self):
        self.save_result()
        evidence = self.root / "new-evidence.json"
        write_evidence(evidence, snapshot(self.context), self.log)
        return verify(self.context, evidence)

    def test_matching_artifacts_pass(self):
        """R1-AC1 G01 Current executed result passes."""
        self.assertEqual(self.verdict()["status"], "PASS")

    def test_each_input_change_invalidates_evidence(self):
        """R1-AC1 G02 Every relevant input hash participates."""
        for role in ["prd", "contract", "data", "code", "tests"]:
            with self.subTest(role=role):
                path = self.root / (role + ".txt")
                original = path.read_bytes()
                path.write_bytes(original + b" changed")
                self.assertEqual(self.verdict()["reason"], "STALE_INPUTS")
                path.write_bytes(original)
        self.assertEqual(self.verdict()["status"], "PASS")

    def test_changed_result_log_is_rejected(self):
        """R1-AC1 G03 Modified observations cannot reuse a record."""
        self.log.write_text("{}", encoding="utf-8")
        self.assertEqual(self.verdict()["reason"], "CHANGED_RESULTS")

    def test_failed_execution_blocks(self):
        """R1-AC1 G04 A failing command cannot complete verification."""
        self.result["returncode"] = 1
        self.assertEqual(self.recapture_result()["reason"], "EXECUTION_FAILED")

    def test_failed_or_unverified_or_skipped_case_blocks(self):
        """R1-AC1 G05 Each case must have actually passed."""
        for status in ["FAIL", "ERROR", "UNVERIFIED", "SKIP"]:
            with self.subTest(status=status):
                self.result["checks"][0]["status"] = status
                self.save_result()
                record = self.root / (status + "-evidence.json")
                write_evidence(record, snapshot(self.context), self.log)
                self.assertEqual(verify(self.context, record)["reason"], "NONPASS_CHECK")

    def test_missing_required_ac_blocks(self):
        """R1-AC1 G06 Required coverage is checked independently."""
        self.result["checks"][0]["ac_ids"] = []
        self.assertEqual(self.recapture_result()["reason"], "MISSING_AC")

    def test_new_required_ac_invalidates_existing_record(self):
        """R1-AC1 G07 Adding acceptance criteria invalidates an old scope."""
        context = json.loads(self.context.read_text())
        context["required_ac"].append("R2-AC2")
        self.context.write_text(json.dumps(context), encoding="utf-8")
        self.assertEqual(self.verdict()["reason"], "STALE_INPUTS")

    def test_duplicate_check_ids_cannot_inflate_coverage(self):
        """R1-AC1 G08 Duplicate test identifiers are rejected."""
        self.result["checks"].append(deepcopy(self.result["checks"][0]))
        self.assertEqual(self.recapture_result()["reason"], "DUPLICATE_CHECK")

    def test_missing_input_roles_cannot_pass(self):
        """R1-AC1 G09 Required source roles cannot be omitted."""
        context = json.loads(self.context.read_text())
        del context["inputs"]["tests"]
        self.context.write_text(json.dumps(context), encoding="utf-8")
        with self.assertRaises(ValueError):
            snapshot(self.context)


class DecisionTransitionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = KIT / "examples/prd_eda_be"
        cls.prd1 = json.loads((source / "prd-v1.json").read_text())
        cls.prd2 = json.loads((source / "prd-v2.json").read_text())
        cls.contract1 = json.loads((source / "contract-v1.json").read_text())
        cls.contract2 = json.loads((source / "contract-v2.json").read_text())
        cls.decisions = json.loads((source / "decisions.json").read_text())["decisions"]

    def test_approved_change_is_applied(self):
        """R2-AC2 G10 Explicit simulated approval applies P2/D2."""
        proposal = deepcopy(self.contract2)
        proposal["status"] = "draft"
        for constraint in proposal["constraints"]:
            constraint["status"] = "proposed"
        prd, contract = apply_decision(
            self.prd1, self.contract1, self.prd2, proposal, self.decisions[0],
        )
        self.assertEqual((prd["revision"], contract["revision"]), ("P2", "D2"))
        self.assertEqual(contract["status"], "confirmed")
        self.assertTrue(all(rule["status"] == "confirmed" for rule in contract["constraints"]))
        self.assertEqual(proposal["status"], "draft")

    def test_rejected_and_pending_keep_original_state(self):
        """R2-AC2 G11 Pending and rejected proposals do not change current state."""
        for decision in self.decisions[1:]:
            with self.subTest(state=decision["state"]):
                self.assertEqual(
                    apply_decision(self.prd1, self.contract1, self.prd2, self.contract2, decision),
                    (self.prd1, self.contract1),
                )

    def test_approval_for_another_revision_is_rejected(self):
        """R2-AC2 G12 Approval must apply to the actual revisions."""
        decision = dict(self.decisions[0], to_prd="P9")
        with self.assertRaises(ValueError):
            apply_decision(self.prd1, self.contract1, self.prd2, self.contract2, decision)
