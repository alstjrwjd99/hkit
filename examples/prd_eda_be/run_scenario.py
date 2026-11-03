"""Run the synthetic PRD -> EDA -> PRD -> BE scenario and save actual evidence."""

import argparse
from contextlib import contextmanager
from copy import deepcopy
import csv
from fractions import Fraction
import io
import json
from pathlib import Path
import re
import subprocess
import sys
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


KIT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / ".agents/skills/check/scripts"))

from examples.prd_eda_be.backend import make_server
from examples.prd_eda_be.workflow import apply_decision
from verify_evidence import digest, snapshot, verify, write_evidence


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path):
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


@contextmanager
def running(prd, contract):
    server = make_server(prd, contract)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/kpi"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def request(url, values):
    payload = json.dumps({"rows": values}).encode("utf-8")
    call = Request(url, payload, {"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(call, timeout=3) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def context(prd_path, contract_path, prd):
    return {
        "schema_version": 1,
        "required_ac": prd["required_ac"],
        "inputs": {
            "prd": [str(prd_path), str(FIXTURES / "prd-v1.json"), str(FIXTURES / "prd-v2.json"),
                    str(FIXTURES / "decisions.json")],
            "contract": [str(contract_path), str(FIXTURES / "contract-v1.json"), str(FIXTURES / "contract-v2.json")],
            "data": [str(FIXTURES / "raw.csv"), str(FIXTURES / "approved.csv")],
            "code": [str(FIXTURES / "backend.py"), str(FIXTURES / "workflow.py"),
                     str(Path(__file__).resolve()), str(KIT / ".agents/skills/eda/scripts/profile_csv.py"),
                     str(KIT / ".agents/skills/check/scripts/verify_evidence.py")],
            "tests": [str(KIT / "tests/test_scenario_backend.py"), str(KIT / "tests/test_verification_evidence.py")],
        },
    }


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.checks = []

    def record(self, test, status):
        self.checks.append({
            "id": test.id(), "ac_ids": sorted(set(re.findall(r"R[0-9]+-AC[0-9]+", test.shortDescription() or ""))),
            "status": status,
        })

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, "PASS")

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.record(test, "FAIL")

    def addError(self, test, error):
        super().addError(test, error)
        self.record(test, "ERROR")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, "SKIP")

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        if error is not None:
            self.record(subtest, "FAIL")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()), "--out", str(output)]
    raw_path = FIXTURES / "raw.csv"
    approved_path = FIXTURES / "approved.csv"
    source_hash = digest(raw_path)

    profile_command = [
        sys.executable, "-X", "utf8", "-B", str(KIT / ".agents/skills/eda/scripts/profile_csv.py"),
        str(raw_path), "--key", "observation_id", "--date", "day=%Y-%m-%d",
        "--prd-revision", "P1", "--contract-out", str(output / "eda-draft.json"),
    ]
    profile_run = subprocess.run(profile_command, capture_output=True, encoding="utf-8", check=True)
    (output / "data-profile.json").write_text(profile_run.stdout, encoding="utf-8")
    profile = json.loads(profile_run.stdout)
    assert profile["duplicate_rows_after_first"] == 1
    assert profile["keys"][0]["duplicate_rows_after_first"] == 1
    assert digest(raw_path) == source_hash
    raw_rows = rows(raw_path)
    unique_rows = {}
    for row in raw_rows:
        key = row["observation_id"]
        if key in unique_rows:
            assert row == unique_rows[key], "Conflicting identities require a separate product decision"
        else:
            unique_rows[key] = row

    def weighted_kpi(values):
        numerator = sum(Fraction(row["demand"]) * Fraction(row["wait_minutes"]) for row in values)
        denominator = sum(Fraction(row["demand"]) for row in values)
        return numerator / denominator

    observed_kpi = weighted_kpi(raw_rows)
    proposed_kpi = weighted_kpi(list(unique_rows.values()))
    assert observed_kpi == Fraction(36, 5) and proposed_kpi == Fraction(8)

    prd1 = load_json(FIXTURES / "prd-v1.json")
    prd2 = load_json(FIXTURES / "prd-v2.json")
    contract1 = load_json(FIXTURES / "contract-v1.json")
    contract2 = load_json(FIXTURES / "contract-v2.json")
    contract1["source"]["sha256"] = source_hash
    contract1["observations"] = profile
    decisions = load_json(FIXTURES / "decisions.json")
    assert decisions["simulation"] is True
    proposal = deepcopy(contract2)
    proposal["status"] = "draft"
    for rule in proposal["constraints"]:
        rule["status"] = "proposed"

    current_prd = output / "prd-current.json"
    current_contract = output / "data-contract-current.json"
    write_json(current_prd, prd1)
    write_json(current_contract, contract1)
    write_json(output / "prd-P1.json", prd1)
    write_json(output / "contract-D1.json", contract1)
    context_path = output / "verification-context.json"
    write_json(context_path, context(current_prd, current_contract, prd1))
    p1_scope = snapshot(context_path)
    with running(prd1, contract1) as url:
        status1, body1 = request(url, rows(raw_path))
        invalid = rows(approved_path)
        invalid[0]["demand"] = "-1"
        invalid_status, _ = request(url, invalid)
    assert status1 == 200 and body1["kpi"] == 7.2
    assert body1["numerator"] == 360 and body1["denominator"] == 50 and body1["rows_used"] == 3
    assert body1["prd_revision"] == "P1" and invalid_status == 422
    old_result = output / "result-P1.json"
    write_json(old_result, {"command": command, "returncode": 0, "http_result": body1, "checks": [
        {"id": "P1-kpi", "ac_ids": ["R1-AC1"], "status": "PASS"},
        {"id": "P1-evidence", "ac_ids": ["R1-AC2"], "status": "PASS"},
        {"id": "P1-validation", "ac_ids": ["R2-AC1"], "status": "PASS"},
    ]})
    old_evidence = output / "evidence-P1.json"
    write_evidence(old_evidence, p1_scope, old_result)
    assert verify(context_path, old_evidence)["status"] == "PASS"

    branches = []
    for decision in decisions["decisions"][1:]:
        unchanged = apply_decision(prd1, contract1, prd2, proposal, decision)
        assert unchanged == (prd1, contract1)
        branches.append({"state": decision["state"], "prd_revision": unchanged[0]["revision"],
                         "contract_revision": unchanged[1]["revision"], "check": "PASS"})
    accepted_prd, accepted_contract = apply_decision(prd1, contract1, prd2, proposal, decisions["decisions"][0])
    assert proposal["status"] == "draft"
    assert rows(approved_path) == list(unique_rows.values())
    approved_profile_command = [
        sys.executable, "-X", "utf8", "-B", str(KIT / ".agents/skills/eda/scripts/profile_csv.py"),
        str(approved_path), "--key", "observation_id", "--date", "day=%Y-%m-%d",
    ]
    approved_profile = subprocess.run(approved_profile_command, capture_output=True, encoding="utf-8", check=True)
    accepted_contract["source"]["sha256"] = digest(approved_path)
    accepted_contract["observations"] = json.loads(approved_profile.stdout)
    write_json(current_prd, accepted_prd)
    write_json(current_contract, accepted_contract)
    write_json(output / "prd-P2.json", accepted_prd)
    write_json(output / "contract-D2.json", accepted_contract)
    write_json(context_path, context(current_prd, current_contract, accepted_prd))
    stale = verify(context_path, old_evidence)
    assert stale == {"status": "BLOCKED", "reason": "STALE_INPUTS"}
    p2_scope = snapshot(context_path)

    with running(accepted_prd, accepted_contract) as url:
        rejected_status, rejected_body = request(url, rows(raw_path))
        status2, body2 = request(url, rows(approved_path))
    assert rejected_status == 422 and status2 == 200
    assert body2["kpi"] == 8 and body2["numerator"] == 240 and body2["denominator"] == 30
    assert body2["rows_used"] == 2 and body2["prd_revision"] == "P2" and body2["contract_revision"] == "D2"

    stream = io.StringIO()
    suite = unittest.TestSuite()
    for pattern in ["test_scenario_backend.py", "test_verification_evidence.py"]:
        suite.addTests(unittest.defaultTestLoader.discover(str(KIT / "tests"), pattern=pattern))
    run = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordingResult).run(suite)
    (output / "test-output.txt").write_text(stream.getvalue(), encoding="utf-8")
    result_path = output / "result-P2.json"
    write_json(result_path, {
        "command": command, "returncode": 0 if run.wasSuccessful() else 1,
        "http_result": body2, "duplicate_rejection": {"status": rejected_status, "body": rejected_body},
        "checks": run.checks,
    })
    current_evidence = output / "evidence-P2.json"
    write_evidence(current_evidence, p2_scope, result_path)
    verdict = verify(context_path, current_evidence)

    def obsolete_expectation():
        """R1-AC1 A P1 KPI expectation must fail against the P2 response."""
        assert body2["kpi"] == 7.2, f"expected 7.2, observed {body2['kpi']}"

    intentional_stream = io.StringIO()
    intentional = unittest.TextTestRunner(
        stream=intentional_stream, verbosity=2, resultclass=RecordingResult,
    ).run(unittest.FunctionTestCase(obsolete_expectation))
    (output / "intentional-failure.txt").write_text(intentional_stream.getvalue(), encoding="utf-8")
    assert not intentional.wasSuccessful()
    failed_result = output / "result-intentional-failure.json"
    write_json(failed_result, {
        "command": command, "returncode": 0 if intentional.wasSuccessful() else 1,
        "actual_kpi": body2["kpi"], "obsolete_expected_kpi": 7.2, "checks": intentional.checks,
    })
    failed_evidence = output / "evidence-intentional-failure.json"
    write_evidence(failed_evidence, p2_scope, failed_result)
    failed_verdict = verify(context_path, failed_evidence)
    assert failed_verdict["status"] == "BLOCKED"
    assert digest(raw_path) == source_hash

    trace = {
        "simulation": True, "source_sha256": source_hash,
        "eda_command": profile_command, "approved_profile_command": approved_profile_command,
        "duplicates": profile["duplicate_rows_after_first"],
        "eda_comparison": {"observed_kpi": float(observed_kpi), "unique_identity_hypothesis_kpi": float(proposed_kpi),
                           "method": "Independent exact Fraction arithmetic before simulated approval"},
        "explain": {"human_decision_required": True, "reason": "Observation identity and duplicate policy change the KPI denominator."},
        "decision_branches": branches + [{"state": "approved", "prd_revision": "P2", "contract_revision": "D2", "check": "PASS"}],
        "P1": body1, "P2": body2, "old_evidence_after_approval": stale,
        "intentional_failure_gate": failed_verdict, "current_verification": verdict,
        "tests_run": run.testsRun, "failures": len(run.failures), "errors": len(run.errors),
    }
    write_json(output / "trace.json", trace)
    report = f"""# PRD → EDA → PRD → BE 통합 검증

이 실행은 합성 버스 데이터와 가상 사용자 승인·거절·보류 입력을 사용했다.

| 단계 | 실제 관찰 |
|---|---|
| PRD P1 / 계약 D1 | HTTP 200, KPI {body1['kpi']}분, 분자 {body1['numerator']}, 분모 {body1['denominator']} |
| EDA | 동일 행·관측 ID 중복 1건, 독립 계산으로 기존 {float(observed_kpi)}분과 고유 관측 가정 {float(proposed_kpi)}분 비교 |
| Explain | 관측 단위·중복 정책이 분모를 바꿔 사용자 판단 필요 |
| 거절·보류 | P1 / D1 유지 |
| 가상 승인 | P2 / D2 적용, 원본 보존·별도 승인 입력 사용 |
| BE P2 원본 입력 | HTTP {rejected_status}, 중복 관측 ID 거부 |
| BE P2 승인 입력 | HTTP {status2}, KPI {body2['kpi']}분, 분자 {body2['numerator']}, 분모 {body2['denominator']} |
| P1 검증 기록 재사용 | {stale['status']} / {stale['reason']} |
| P2에 P1 기대값 적용 | {failed_verdict['status']} / {failed_verdict['reason']} |
| 현재 검증 | {verdict['status']}, 실제 HTTP·워크플로·검증 게이트 {run.testsRun}개 테스트 |

test-output.txt에 테스트별 실행 결과, trace.json에 단계별 관찰값,
evidence-P1.json과 evidence-P2.json에 입력·결과 해시가 있다.
PRD·계약·데이터·코드·테스트 파일 각각의 변경, 결과 로그 변조, 실패·미검증·누락 AC 차단을 회귀 테스트로 확인했다.

원본 SHA-256은 실행 전후 동일하다. 사용자 결정은 가상 입력이다.
이 예제의 BE는 표준 라이브러리의 로컬 계산 API이며, 실제 과제 앱과 UI 검증은 별도로 수행한다.
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"status": verdict["status"], "tests_run": run.testsRun, "report": str(output / "report.md")}, ensure_ascii=False))
    return 0 if verdict["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
