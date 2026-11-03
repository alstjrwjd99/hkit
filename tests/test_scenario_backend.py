"""Use-case API regressions for the PRD → EDA → PRD → BE example."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import csv
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import unittest

from examples.prd_eda_be.backend import make_server


FIXTURES = Path(__file__).resolve().parents[1] / "examples" / "prd_eda_be"


def load_json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_rows(name):
    with (FIXTURES / name).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


@contextmanager
def running_server(prd, contract):
    server = make_server(prd, contract)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


class ScenarioBackendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prd1 = load_json("prd-v1.json")
        cls.prd2 = load_json("prd-v2.json")
        cls.contract1 = load_json("contract-v1.json")
        cls.contract2 = load_json("contract-v2.json")
        cls.raw_rows = load_rows("raw.csv")
        cls.approved_rows = load_rows("approved.csv")
        cls.servers = ExitStack()
        cls.addClassCleanup(cls.servers.close)
        cls.url1 = cls.servers.enter_context(running_server(cls.prd1, cls.contract1))
        cls.url2 = cls.servers.enter_context(running_server(cls.prd2, cls.contract2))

    def request(self, rows=None, *, payload=None, raw=None, path="/kpi", base=None):
        if raw is None:
            if payload is None:
                payload = {"rows": self.approved_rows if rows is None else rows}
            raw = json.dumps(payload).encode("utf-8")
        request = Request(
            (base or self.url2) + path, data=raw, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def assert_error(self, expected_status, rows=None, **options):
        status, body = self.request(rows, **options)
        self.assertEqual(status, expected_status, body)
        self.assertIsInstance(body.get("error"), dict, body)
        self.assertIsInstance(body["error"].get("code"), str, body)
        self.assertTrue(body["error"]["code"], body)
        self.assertIsInstance(body["error"].get("message"), str, body)

    def changed_rows(self, **values):
        rows = deepcopy(self.approved_rows)
        rows[0].update(values)
        return rows

    def test_b01_approved_kpi(self):
        """B01 R1-AC1 Approved two-observation KPI equals the independent calculation."""
        status, body = self.request()
        self.assertEqual(status, 200, body)
        self.assertEqual(body["kpi"], 8)
        self.assertEqual(body["numerator"], 240)
        self.assertEqual(body["denominator"], 30)

    def test_b02_observation_and_revision_evidence(self):
        """B02 R1-AC2 Successful response names the exact current PRD and contract."""
        status, body = self.request()
        self.assertEqual(status, 200, body)
        self.assertEqual(body["rows_used"], 2)
        self.assertEqual(body["prd_revision"], "P2")
        self.assertEqual(body["contract_revision"], "D2")

    def test_b03_p1_counts_duplicate_rows(self):
        """B03 R1-AC1 Historical P1 applies its original row-grain calculation."""
        status, body = self.request(self.raw_rows, base=self.url1)
        self.assertEqual(status, 200, body)
        self.assertAlmostEqual(body["kpi"], 7.2)
        self.assertEqual(body["numerator"], 360)
        self.assertEqual(body["denominator"], 50)
        self.assertEqual(body["rows_used"], 3)
        self.assertEqual(body["prd_revision"], "P1")

    def test_b04_p2_rejects_exact_duplicate(self):
        """B04 R2-AC2 Current unique-ID contract rejects exact duplicate observations."""
        self.assert_error(422, self.raw_rows)

    def test_b05_json_numeric_values(self):
        """B05 R1-AC1 JSON numbers and CSV numeric strings have the same semantics."""
        rows = deepcopy(self.approved_rows)
        for row in rows:
            row["demand"] = int(row["demand"])
            row["wait_minutes"] = int(row["wait_minutes"])
        status, body = self.request(rows)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["kpi"], 8)

    def test_b06_multiple_routes_use_passenger_weights(self):
        """B06 R1-AC1 Total KPI aggregates weighted sums across different routes."""
        rows = deepcopy(self.approved_rows)
        rows[1]["route"] = "B"
        rows[1]["demand"] = "30"
        status, body = self.request(rows)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["numerator"], 300)
        self.assertEqual(body["denominator"], 40)
        self.assertEqual(body["kpi"], 7.5)

    def test_b07_fractional_weights_and_waits(self):
        """B07 R1-AC1 Fractional inputs preserve the expected weighted calculation."""
        rows = self.changed_rows(demand="0.1", wait_minutes="0.2")
        rows[1].update(demand="0.3", wait_minutes="0.4")
        status, body = self.request(rows)
        self.assertEqual(status, 200, body)
        self.assertAlmostEqual(body["numerator"], 0.14)
        self.assertAlmostEqual(body["denominator"], 0.4)
        self.assertAlmostEqual(body["kpi"], 0.35)

    def test_b08_zero_wait_is_valid_lower_boundary(self):
        """B08 R1-AC1 R2-AC1 Zero waiting time is valid with positive demand."""
        rows = self.changed_rows(wait_minutes=0)
        rows[1]["wait_minutes"] = 0
        status, body = self.request(rows)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["kpi"], 0)

    def test_b09_zero_demand_row_with_nonzero_total(self):
        """B09 R1-AC1 R2-AC1 A zero-weight observation does not change a defined KPI."""
        status, body = self.request(self.changed_rows(demand=0))
        self.assertEqual(status, 200, body)
        self.assertEqual(body["kpi"], 6)
        self.assertEqual(body["denominator"], 20)
        self.assertEqual(body["rows_used"], 2)

    def test_b10_period_start_is_inclusive(self):
        """B10 R2-AC1 The first day in the PRD period is accepted."""
        status, body = self.request(self.changed_rows(day="2026-11-01"))
        self.assertEqual(status, 200, body)

    def test_b11_period_end_is_inclusive(self):
        """B11 R2-AC1 The last day in the PRD period is accepted."""
        status, body = self.request(self.changed_rows(day="2026-11-03"))
        self.assertEqual(status, 200, body)

    def test_b12_missing_required_fields(self):
        """B12 R2-AC1 Every confirmed required field is enforced."""
        for name in ["observation_id", "route", "day", "demand", "wait_minutes"]:
            with self.subTest(field=name):
                rows = deepcopy(self.approved_rows)
                del rows[0][name]
                self.assert_error(422, rows)

    def test_b13_whitespace_required_field(self):
        """B13 R2-AC1 Whitespace-only observation identity is treated as missing."""
        self.assert_error(422, self.changed_rows(observation_id=" \t "))

    def test_b14_null_numeric_input(self):
        """B14 R2-AC1 Null demand is rejected rather than converted to zero."""
        self.assert_error(422, self.changed_rows(demand=None))

    def test_b15_boolean_is_not_a_numeric_measurement(self):
        """B15 R2-AC1 Boolean input is rejected for each numeric measurement."""
        for name in ["demand", "wait_minutes"]:
            with self.subTest(field=name):
                self.assert_error(422, self.changed_rows(**{name: True}))

    def test_b16_nonfinite_values(self):
        """B16 R2-AC1 Numeric strings and JSON non-finite values are rejected."""
        for value in ["NaN", "Infinity", "-Infinity", float("nan"), float("inf")]:
            with self.subTest(value=repr(value)):
                self.assert_error(422, self.changed_rows(demand=value))

    def test_b17_negative_demand(self):
        """B17 R2-AC1 Demand immediately below the confirmed minimum is rejected."""
        self.assert_error(422, self.changed_rows(demand="-0.01"))

    def test_b18_negative_wait(self):
        """B18 R2-AC1 Negative waiting time is rejected."""
        self.assert_error(422, self.changed_rows(wait_minutes="-1"))

    def test_b19_invalid_calendar_date(self):
        """B19 R2-AC1 A date matching the lexical shape must still be a valid day."""
        self.assert_error(422, self.changed_rows(day="2026-11-31"))

    def test_b20_day_before_period(self):
        """B20 R2-AC1 The day immediately before the PRD period is rejected."""
        self.assert_error(422, self.changed_rows(day="2026-10-31"))

    def test_b21_day_after_period(self):
        """B21 R2-AC1 The day immediately after the PRD period is rejected."""
        self.assert_error(422, self.changed_rows(day="2026-11-04"))

    def test_b22_zero_denominator(self):
        """B22 R2-AC1 A zero passenger denominator produces a validation error."""
        rows = deepcopy(self.approved_rows)
        for row in rows:
            row["demand"] = 0
        self.assert_error(422, rows)

    def test_b23_empty_observation_set(self):
        """B23 R2-AC1 An empty observation set has no valid KPI."""
        self.assert_error(422, [])

    def test_b24_malformed_json(self):
        """B24 R2-AC1 Malformed JSON is rejected before business validation."""
        self.assert_error(400, raw=b'{"rows": [')

    def test_b25_invalid_payload_shapes(self):
        """B25 R2-AC1 Request and row collection shapes are validated."""
        for payload in [[], None, {}, {"rows": None}, {"rows": "text"}, {"rows": [1]}]:
            with self.subTest(payload=payload):
                self.assert_error(400, raw=json.dumps(payload).encode("utf-8"))

    def test_b26_unknown_route(self):
        """B26 R2-AC1 An unregistered API path produces a structured 404 response."""
        self.assert_error(404, path="/missing")

    def test_b27_failed_request_does_not_poison_next_call(self):
        """B27 R1-AC1 R2-AC1 A valid retry succeeds after a rejected request."""
        self.assert_error(422, self.changed_rows(demand=-1))
        status, body = self.request()
        self.assertEqual(status, 200, body)
        self.assertEqual(body["kpi"], 8)

    def test_b28_concurrent_calculations(self):
        """B28 R1-AC1 Concurrent identical calls produce independent equal results."""
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: self.request(), range(4)))
        self.assertTrue(all(status == 200 for status, _ in responses))
        self.assertEqual([body["kpi"] for _, body in responses], [8, 8, 8, 8])

    def test_b29_draft_contract_is_not_activated(self):
        """B29 R2-AC1 A draft data contract cannot configure the backend."""
        contract = deepcopy(self.contract2)
        contract["status"] = "draft"
        with self.assertRaises(ValueError):
            make_server(self.prd2, contract)

    def test_b30_prd_contract_revision_mismatch(self):
        """B30 R2-AC1 A contract linked to P1 cannot configure P2."""
        with self.assertRaises(ValueError):
            make_server(self.prd2, self.contract1)

    def test_b31_unsupported_rule(self):
        """B31 R2-AC1 An unknown confirmed constraint rule fails configuration."""
        contract = deepcopy(self.contract2)
        contract["constraints"][0]["rule"] = "unknown-rule"
        with self.assertRaises(ValueError):
            make_server(self.prd2, contract)

    def test_b32_unsupported_contract_schema(self):
        """B32 R2-AC1 An unsupported contract schema version fails configuration."""
        contract = deepcopy(self.contract2)
        contract["schema_version"] = 999
        with self.assertRaises(ValueError):
            make_server(self.prd2, contract)

    def test_b33_proposed_rule_is_not_enforced(self):
        """B33 R2-AC1 A proposed uniqueness rule does not alter the P1 contract."""
        contract = deepcopy(self.contract1)
        candidate = deepcopy(self.contract2["constraints"][-1])
        candidate["status"] = "proposed"
        contract["constraints"].append(candidate)
        with running_server(self.prd1, contract) as base:
            status, body = self.request(self.raw_rows, base=base)
        self.assertEqual(status, 200, body)
        self.assertAlmostEqual(body["kpi"], 7.2)

    def test_b34_conflicting_values_for_one_identity(self):
        """B34 R2-AC2 Two distinct payloads with one observation ID are rejected."""
        rows = deepcopy(self.approved_rows)
        rows[1]["observation_id"] = rows[0]["observation_id"]
        self.assert_error(422, rows)

    def test_b35_updated_range_is_consumed(self):
        """B35 R2-AC1 An explicit new upper bound is applied at its boundary."""
        contract = deepcopy(self.contract2)
        rule = next(item for item in contract["constraints"] if item["id"] == "D-RANGE-wait_minutes")
        rule["parameters"]["max"] = "10"
        with running_server(self.prd2, contract) as base:
            self.assert_error(422, self.approved_rows, base=base)
            status, body = self.request(self.changed_rows(wait_minutes="10"), base=base)
        self.assertEqual(status, 200, body)

    def test_b36_composite_uniqueness_is_consumed(self):
        """B36 R2-AC2 Composite uniqueness uses all configured key columns."""
        contract = deepcopy(self.contract2)
        rule = deepcopy(contract["constraints"][-1])
        rule.update(id="D-COMPOSITE", columns=["route", "day"])
        contract["constraints"].append(rule)
        with running_server(self.prd2, contract) as base:
            rows = self.changed_rows(day="2026-11-02")
            self.assert_error(422, rows, base=base)
            status, body = self.request(self.approved_rows, base=base)
        self.assertEqual(status, 200, body)


if __name__ == "__main__":
    unittest.main()
