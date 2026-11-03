# hkit

제한 시간 안에 과제의 핵심 기능을 구현하고, 사람이 그 판단과 검증 근거를 설명할 수 있게 돕는 Codex 작업 키트다. 기존 서비스, 문제 지시, 데이터가 있는 **과제 폴더**에 설치해서 쓴다.

## 시작

Bash(Windows에서는 Git Bash)에서 실행한다. 과제 폴더가 이미 있어야 한다.

```sh
bash /path/to/hkit/install.sh "/path/to/task"
cd "/path/to/task"
codex
```

과제 루트에서 새 Codex 세션을 열고 아래처럼 요청한다.

> $plan 과제 지시와 데이터를 읽고 PRD와 기준선을 정리해 줘. 내가 선택해야 할 KPI가 있으면 비교 결과를 먼저 보여 줘. 핵심 검토 후 API 계약을 확정하고, 파일을 독립적으로 나눌 수 있으면 frontend와 backend 서브에이전트를 병렬로 써 줘. 마지막에 필수 AC별 실제 결과를 확인해 줘.

설치기는 기존 파일과 같은 이름의 스킬 디렉터리를 보존한다. 기존 `AGENTS.md`가 있으면 설치 결과에 표시되는 `HYNIX_KIT_GUIDE.md`도 보조 지침으로 읽도록 요청한다. 이전 키트가 설치돼 있으면 `KEEP`으로 표시된 파일의 변경분은 과제 담당자가 비교해 선별 반영한다. 과제 지정 문서와 이미 작성한 기록을 우선하며, 같은 내용을 새 양식에 옮겨 적지 않는다.

## 한 과제의 진행 순서

| 단계 | 누가 무엇을 하는가 | 다음 단계로 넘기는 결과 |
|---|---|---|
| 문제와 데이터 | 메인 세션이 `$plan`에서 `$prd`를 작성하고, 가설·품질·KPI 검증이 필요하면 `$eda`를 호출한다. 반환된 근거로 PRD를 갱신하고 바뀐 조건을 재검증한다. | 요구 ID별 수용 기준, 재현 가능한 기준선, 사람이 검토한 범위 |
| 계약 | 메인 세션이 FE와 BE가 같은 요청에 기대하는 타입·예외·응답을 확정한다. | 양쪽이 실행할 성공/오류 예, 소유 경로 |
| 구현 | `$build`에서 `$frontend`와 `$backend`를 사용한다. 병렬 실행이 허용되고 경로가 분리되면 동명의 서브에이전트에게 맡긴다. 그 외에는 한 세션에서 순서대로 진행한다. | 사용자 화면과 시나리오 테스트, API·데이터 모델과 로직 테스트 |
| 통합 검증과 인계 | 메인 세션이 `$check`에서 실제 사용자 흐름·반례·KPI를 확인하고 `$finish`로 인계한다. `$explain`은 어느 단계에서든 중요한 대안과 실제 결정을 기록한다. | AC별 판정과 재현 절차, 실제 결정과 남은 한계 |

문제 정의·1차 KPI·우선순위·범위는 사람이 결정한다. 실제 과제의 타이머와 운영 규칙에 맞춰 선택 기능을 줄인다. 모델과 앱 기술 스택은 프로젝트 설정을 따른다.

### FE 테마 선택

FE는 표시할 정보, 여백을 줄인 무채색 배치, 중요도별 배경, 버튼 강조, 컴포넌트별 두 색 점검 순으로 화면을 만든다. 메인 컬러는 착수할 때 골라 두고 배치가 정해진 뒤 주 버튼에 적용한다. 과제와 기존 앱에 테마가 없으면 중립색을 쓰고, 특정 브랜드를 원하면 첫 요청에 “하이닉스 테마” 또는 “크래프톤 테마”를 덧붙인다.

키트에는 중립 메인 컬러(파랑), 성공·주의·실패 상태색과 두 브랜드 프리셋이 들어 있다. 하이닉스 프리셋은 SK Red를, 크래프톤 프리셋은 KRAFTON Black을 주 버튼색으로 쓴다. [키트 색상 토큰](.agents/skills/frontend/assets/theme.css) · [SK하이닉스 CI](https://www.skhynix.com/company/UI-FR-CP0402/) · [크래프톤 브랜드 가이드](https://www.krafton.com/wp-content/uploads/2021/07/20210721_KRAFTON_BrandGuide_Ex_Kr.pdf#page=22)

### BE 유스케이스 테스트

BE는 PRD의 유스케이스에서 정상·실패·경계 시나리오를 약 30건 도출하고 각 시나리오를 AC와 테스트에 연결한다. 입력·권한·상태 전이·계산·저장 실패 중 실제 기능에 해당하는 조건을 덮고, 과제 규모에 따라 개수와 우선순위를 조정한다. 단위 테스트와 실제 앱·테스트 저장소를 통한 API 통합 테스트를 실행하고, 시나리오 수와 PASS/FAIL/미검증, 남은 업무 분기를 검증표에 기록한다.

### EDA 호출과 인계

데이터 가설 검증, 품질이 구현·정확도에 미치는 영향, KPI·기준선 비교 중 하나가 필요하면 EDA를 수행한다. 단순 구조 점검은 메인 세션에서, 복잡한 통계·여러 가설·큰 데이터 반복 처리는 허용되는 경우 eda 서브에이전트에서 수행한다. 분석에 쓸 자원과 파일 경로를 지정하고 메인 세션은 결론과 산출물 경로를 회수한다.

PRD는 리비전·가설·관련 AC·산식·대상·입력과 필요한 결정을 전달한다. EDA는 품질과 기준선의 재현 근거, 요구 및 BE 테스트 변경 제안을 반환한다. 메인 세션이 수용·수정·보류한 뒤, 변경된 가설이나 산식·입력만 다시 검증한다. 문제 정의·주 KPI·우선순위·범위 변경은 사람이 결정한다.

프로파일러는 Python 3.11 이상에서 동작하며 CP949 지정, 열별 타입·결측률·숫자 범위·날짜 검사·복합키 점검을 지원한다. 다음 명령의 경로·열·인코딩은 과제 데이터에 맞춰 바꾼다.

```sh
python3 .agents/skills/eda/scripts/profile_csv.py data/input.csv --encoding cp949 --key route_id,stop_id --date service_date=%Y-%m-%d --prd-revision P1 --contract-out docs/data-contract.json > docs/data-profile.json
```

출력 계약은 초안이며 관찰값과 빈 제약 목록을 담는다. 메인 세션이 요구와 근거에 맞는 제약을 확정하면 BE가 해당 계약의 입력 검증과 테스트를 구현한다. 파일이 이미 있으면 새 리비전 경로를 사용한다. 큰 파일은 `--max-rows N`으로 초기 탐색 범위를 제한할 수 있으며, 이때 전수 확인이 필요한 제약을 추가 검증한다. [데이터 계약 규격](.agents/skills/eda/references/data-contract.md)

## 설치된 과제에서 찾을 파일

| 경로 | 용도 |
|---|---|
| `SPEC.md` | 요구의 출처, 필수/선택, AC 참조, 핵심 검토와 우선순위 |
| `docs/prd.md` | 사용자의 문제와 흐름, KPI, 수용 기준 |
| `docs/data-report.md` | 데이터 품질, 분석 스크립트·실행 명령, 기준선과 한계 |
| `docs/data-contract.json` | EDA 실행 시 생성하는 관찰값과 확정 제약의 기계 판독 계약 |
| `docs/api-contract.md` | FE·BE 계약과 소유 경로 |
| `docs/decision-log.md` | 중요한 대안과 근거, 확정 여부와 결정 주체 |
| `docs/verification.md` | AC별 테스트·KPI·실제 화면의 관찰값과 판정 |
| `EVIDENCE.md` | 검증·결정 기록을 가리키는 제출 전 인계와 실행 방법 |

키트의 양식 원본은 `templates/`에 있다. 앱과 도메인 분석 스크립트는 실제 과제에 맞춰 만든다. CSV/TSV 초기 점검은 설치 후 `python3 .agents/skills/eda/scripts/profile_csv.py data/input.csv`로 실행할 수 있다.

설치기나 분석 스크립트를 변경한 뒤에는 키트 루트에서 `python3 -m unittest discover -s tests -v`로 새 설치, 재설치, 기존 파일 보존과 프로파일링·계약 생성을 재검증할 수 있다. 이 테스트는 PATH에 Bash가 있는 환경에서 실행한다.

PRD → EDA → PRD → BE 통합 예제는 키트 루트에서 아래처럼 실행한다. 출력에는 단계별 관찰, 실제 HTTP 테스트 결과, 이전·현재 검증 기록과 해시를 저장한다. 합성 버스 데이터와 가상 승인·거절·보류를 사용하며 출력 폴더는 새 경로를 지정한다.

```sh
python3 examples/prd_eda_be/run_scenario.py --out /path/to/new-run
```

승인 후 중복 입력은 HTTP 422로 거부하고 승인된 입력의 KPI를 계산한다. PRD·계약·데이터·코드·테스트가 달라지면 이전 검증 기록을 차단한다. 과제에서도 같은 형식으로 검증 기록을 연결할 수 있다. [검증 기록 규격](.agents/skills/check/references/evidence.md)

브라우저에서 같은 흐름을 보려면 로컬 프론트를 실행한다. 앞서 생성한 검증 출력 폴더를 연결하면 기록 확인 버튼에서 실제 해시 검사 결과를 볼 수 있다.

```sh
python3 examples/prd_eda_be/web_server.py --port 8765 --evidence-dir /path/to/new-run
```

터미널에 표시된 로컬 주소를 연다. 원본·승인 입력 선택, 수요·대기시간 수정, 가상 승인·거절·보류, 실제 BE 계산, 이전 검증 기록 차단을 제공한다. 중립·하이닉스·크래프톤 테마를 바꿀 수 있으며, 화면 상태는 새로고침하면 초기화된다.

## 참고한 설계

pstack의 [Feature](https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-mode/playbooks/feature.md)에서 선행 조건과 독립 작업 분리를, [Architect](https://github.com/cursor/plugins/blob/main/pstack/skills/architect/SKILL.md)에서 호출 예와 모듈 경계 확정을 가져왔다. [Interrogate](https://github.com/cursor/plugins/blob/main/pstack/skills/interrogate/SKILL.md)의 반례 재현과 [Prove It Works](https://github.com/cursor/plugins/blob/main/pstack/skills/principle-prove-it-works/SKILL.md)의 실제 결과 확인은 공통 검증 단계에 반영했다.

프로젝트 스킬과 서브에이전트 형식은 [OpenAI Docs의 스킬 문서](https://developers.openai.com/codex/skills)와 [서브에이전트 문서](https://developers.openai.com/codex/subagents)를 따른다.
