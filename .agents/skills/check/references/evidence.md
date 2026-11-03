# 실행 결과와 현재 입력의 연결

## Context

현재 작업의 검증 범위를 JSON 파일에 선언한다. 경로는 context 파일 기준 상대 경로나 절대 경로를 사용한다. 다섯 입력 역할에 각각 파일을 하나 이상 지정하고 필수 AC를 현재 PRD와 대조한다.

```json
{
  "schema_version": 1,
  "required_ac": ["R1-AC1", "R2-AC1"],
  "inputs": {
    "prd": ["prd.md"],
    "contract": ["data-contract.json"],
    "data": ["../data/input.csv"],
    "code": ["../backend.py"],
    "tests": ["../tests/test_backend.py"]
  }
}
```

실행에 영향을 주는 공유 타입·설정·규칙·의존성 파일도 해당 역할의 목록에 포함한다. PRD의 필수 AC와 입력 목록을 선택하는 책임은 오케스트레이터에게 있다.

## 실행 기록

검증 전에 `scripts/verify_evidence.py`의 `snapshot(context_path)`으로 경로·SHA-256·필수 AC를 캡처한다. 테스트를 실제 실행해 다음 결과 JSON을 저장한 뒤 `write_evidence(evidence_path, scope_before_execution, result_path)`로 연결한다. 출력 evidence 파일은 새 경로를 사용한다.

```json
{
  "command": ["python3", "-m", "unittest", "discover", "-s", "tests"],
  "returncode": 0,
  "checks": [
    {"id": "B01", "ac_ids": ["R1-AC1"], "status": "PASS"},
    {"id": "B02", "ac_ids": ["R2-AC1"], "status": "PASS"}
  ]
}
```

명령·종료 코드와 테스트별 판정은 실제 runner 결과에서 기록한다. 미실행·건너뜀·오류·실패를 그대로 남기고, 동일 테스트 ID는 한 번만 쓴다. 결과 로그의 해시도 evidence에 보관한다. 실행기 연결 예는 키트의 `examples/prd_eda_be/run_scenario.py`에 있다.

## 완료 판정

```sh
python3 .agents/skills/check/scripts/verify_evidence.py --context docs/verification-context.json --evidence docs/evidence.json
```

현재 경로·입력 해시·필수 AC가 캡처 시점과 같고, 결과 로그가 보존돼 있으며, 실행과 모든 테스트가 PASS이고 필수 AC가 연결됐을 때 종료 코드 0과 PASS를 반환한다. 입력 변경, 로그 변조, 실패·미검증·누락은 BLOCKED와 종료 코드 1로 반환한다.

새 PRD나 계약이 적용되면 현재 context를 갱신하고 영향받는 테스트를 실행해 새 evidence를 만든다. 기존 결과는 원래 리비전의 이력으로 보존한다. 가상 사용자 결정을 사용한 시험은 simulation으로 표시하고 실제 제품 결정과 구별한다.
