"use strict";

const $ = (id) => document.getElementById(id);
const clone = (value) => structuredClone(value);
const state = {
  bootstrap: null,
  dataset: "raw",
  rows: [],
  decision: "pending",
  revision: "p1",
  requestVersion: 0,
  controller: null,
  hasRun: false,
  verificationVersion: 0,
  activity: [],
};
const clock = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
});
const number = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 3 });

async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  const body = await response.json();
  return { status: response.status, body };
}

function validationMessage(message) {
  if (message.includes("Duplicate")) return "같은 관측 ID가 반복됩니다. 승인 입력을 선택하거나 입력을 확인하세요.";
  if (message.includes("denominator is zero")) return "수요의 합이 0이라 가중 평균을 계산할 수 없습니다.";
  if (message.includes("outside the PRD period")) return "관측 날짜가 PRD의 평가 기간을 벗어났습니다.";
  const fields = { demand: "수요", wait_minutes: "대기시간" };
  for (const [field, label] of Object.entries(fields)) {
    if (message === field + " is below its minimum") return label + " 값이 계약의 최솟값보다 작습니다.";
    if (message === field + " is above its maximum") return label + " 값이 계약의 최댓값보다 큽니다.";
    if (message === field + " is required") return label + " 값을 입력하세요.";
  }
  if (message.includes("finite number")) return "수요와 대기시간에 유효한 숫자를 입력하세요.";
  return "입력값이 현재 계약을 충족하는지 확인하세요. 응답 상세에서 오류 원인을 볼 수 있습니다.";
}

function log(message) {
  state.activity.unshift({ time: clock.format(new Date()), message });
  state.activity = state.activity.slice(0, 5);
  $("activity-list").replaceChildren(...state.activity.map((entry) => {
    const item = document.createElement("li");
    const time = document.createElement("span");
    time.className = "activity-time";
    time.textContent = entry.time;
    const text = document.createElement("span");
    text.textContent = entry.message;
    item.append(time, text);
    return item;
  }));
}

function currentVersion() {
  return state.bootstrap.revisions[state.revision];
}

function invalidate(message) {
  state.requestVersion += 1;
  state.controller?.abort();
  $("calculate").disabled = !state.bootstrap;
  $("calculate").textContent = "계산 실행 ↗";
  $("pipeline-result").textContent = state.hasRun ? "재계산 필요" : "실행 전";
  $("request-status").textContent = message;
  if (state.hasRun) {
    $("result-label").textContent = "이전 실행값 · 재계산 필요";
    $("live-value").classList.add("stale-value");
  }
}

function renderRows() {
  const counts = new Map();
  for (const row of state.rows) counts.set(row.observation_id, (counts.get(row.observation_id) || 0) + 1);
  $("data-body").replaceChildren(...state.rows.map((row, index) => {
    const tr = document.createElement("tr");
    for (const field of ["observation_id", "route", "day", "demand", "wait_minutes"]) {
      const cell = document.createElement("td");
      if (field === "demand" || field === "wait_minutes") {
        cell.className = "numeric";
        const input = document.createElement("input");
        input.type = "number";
        input.step = "any";
        input.value = row[field];
        input.setAttribute("aria-label", (index + 1) + "행 " + row.observation_id + (field === "demand" ? " 수요" : " 대기시간"));
        input.addEventListener("input", () => {
          state.rows[index][field] = input.value;
          invalidate("입력이 변경됐습니다. 현재 계약으로 다시 계산하세요.");
        });
        cell.append(input);
      } else {
        cell.textContent = row[field];
      }
      tr.append(cell);
    }
    const status = document.createElement("td");
    const label = document.createElement("span");
    label.className = "observation-state";
    label.textContent = counts.get(row.observation_id) > 1 ? "중복 후보" : "고유 관측";
    status.append(label);
    tr.append(status);
    return tr;
  }));
  const duplicates = [...counts.values()].reduce((sum, count) => sum + Math.max(0, count - 1), 0);
  $("row-summary").textContent = state.rows.length + "행 · 중복 관측 ID " + duplicates + "건";
  $("raw-data").setAttribute("aria-pressed", String(state.dataset === "raw"));
  $("approved-data").setAttribute("aria-pressed", String(state.dataset === "approved"));
  $("data-description").textContent = state.dataset === "raw"
    ? "동일한 관측 ID O2가 두 행에 있습니다. 수요와 대기시간을 수정해 경계값도 확인할 수 있습니다."
    : "관측 ID가 고유한 예제 입력입니다. 데이터 선택과 적용 계약은 각각 변경할 수 있습니다.";
}

// 비교 열의 표는 읽기 전용으로 각 정책이 집계하는 데이터셋을 그대로 보여 준다
function renderCompareRows(id, rows) {
  const counts = new Map();
  for (const row of rows) counts.set(row.observation_id, (counts.get(row.observation_id) || 0) + 1);
  $(id).replaceChildren(...rows.map((row) => {
    const tr = document.createElement("tr");
    for (const field of ["observation_id", "route", "day", "demand", "wait_minutes"]) {
      const cell = document.createElement("td");
      if (field === "demand" || field === "wait_minutes") cell.className = "numeric";
      cell.textContent = row[field];
      tr.append(cell);
    }
    const status = document.createElement("td");
    const label = document.createElement("span");
    label.className = "observation-state";
    label.textContent = counts.get(row.observation_id) > 1 ? "중복 후보" : "고유 관측";
    status.append(label);
    tr.append(status);
    return tr;
  }));
}

function selectDataset(dataset) {
  if (!state.bootstrap) return;
  state.dataset = dataset;
  state.rows = clone(state.bootstrap.datasets[dataset]);
  renderRows();
  invalidate("입력 데이터가 변경됐습니다. 현재 계약으로 다시 계산하세요.");
  log(dataset === "raw" ? "원본 3행 선택" : "고유 관측의 승인 입력 2행 선택");
}

function decide(decision) {
  if (!state.bootstrap) return;
  state.decision = decision;
  state.revision = decision === "approved" ? "p2" : "p1";
  const version = currentVersion();
  const label = version.prd.revision + " / " + version.contract.revision;
  const description = { approved: "가상 승인 적용", rejected: "가상 거절", pending: "가상 보류" }[decision];
  $("current-revision").textContent = label;
  $("pipeline-contract").textContent = label;
  $("compare-p1").classList.toggle("is-current", state.revision === "p1");
  $("compare-p2").classList.toggle("is-current", state.revision === "p2");
  $("pipeline-decision").textContent = description;
  $("decision-state").textContent = description + " · " + label + (decision === "approved" ? " 적용" : " 유지");
  for (const [id, value] of [["approve", "approved"], ["reject", "rejected"], ["defer", "pending"]]) {
    $(id).setAttribute("aria-pressed", String(decision === value));
  }
  invalidate(decision === "approved"
    ? "P2 / D2를 적용했습니다. 원본 입력에는 중복 ID가 있어 검증이 실패합니다."
    : "P1 / D1을 유지합니다. 현재 입력으로 계산할 수 있습니다.");
  log(description + " · " + label);
}

async function calculate() {
  if (!state.bootstrap) return;
  state.controller?.abort();
  const controller = new AbortController();
  state.controller = controller;
  const version = ++state.requestVersion;
  const revision = state.revision;
  const expected = currentVersion();
  $("calculate").disabled = true;
  $("calculate").textContent = "계산 중…";
  $("request-status").textContent = "로컬 BE API에서 입력과 계약을 검증하고 있습니다.";
  try {
    const response = await api("/api/kpi/" + revision, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows: clone(state.rows) }),
      signal: controller.signal,
    });
    if (version !== state.requestVersion) return;
    state.hasRun = true;
    $("live-value").classList.remove("stale-value");
    $("response-json").textContent = JSON.stringify({ http_status: response.status, ...response.body }, null, 2);
    if (response.status === 200) {
      if (response.body.prd_revision !== expected.prd.revision || response.body.contract_revision !== expected.contract.revision) {
        throw new Error("응답의 PRD·계약 리비전이 요청과 다릅니다.");
      }
      $("live-value").textContent = number.format(response.body.kpi);
      $("live-unit").textContent = "분";
      $("result-label").textContent = "현재 실행 결과";
      $("request-status").textContent = "HTTP 200 · " + response.body.rows_used + "행 · 분자 " + response.body.numerator + " / 분모 " + response.body.denominator;
      $("pipeline-result").textContent = "계산 완료 · HTTP 200";
      log(expected.prd.revision + " / " + expected.contract.revision + " 계산 · " + number.format(response.body.kpi) + "분");
    } else {
      $("live-value").textContent = "—";
      $("live-unit").textContent = "";
      $("result-label").textContent = "입력 검증 실패";
      const message = response.body.error?.message || "입력을 확인하세요.";
      const detail = validationMessage(message);
      $("request-status").textContent = "HTTP " + response.status + " · " + detail;
      $("pipeline-result").textContent = "검증 실패 · HTTP " + response.status;
      log("입력 검증 실패 · HTTP " + response.status);
    }
  } catch (error) {
    if (error.name === "AbortError" || version !== state.requestVersion) return;
    $("request-status").textContent = "요청 실패 · " + error.message + " 다시 실행할 수 있습니다.";
    $("pipeline-result").textContent = "연결 확인 필요";
    $("live-value").textContent = "—";
    $("live-unit").textContent = "";
    $("result-label").textContent = "요청 실패";
    $("response-json").textContent = JSON.stringify({
      request_error: error.message,
      requested_prd: expected.prd.revision,
      requested_contract: expected.contract.revision,
    }, null, 2);
    log("API 요청 실패 · 다시 실행 가능");
  } finally {
    if (version === state.requestVersion) {
      $("calculate").disabled = false;
      $("calculate").textContent = "계산 실행 ↗";
    }
  }
}

async function verifyRecord() {
  const record = $("record").value;
  const version = ++state.verificationVersion;
  $("verify").disabled = true;
  $("verification-status").textContent = "저장된 검증 범위와 현재 파일을 확인하고 있습니다.";
  try {
    const response = await api("/api/evidence?record=" + encodeURIComponent(record));
    if (version !== state.verificationVersion) return;
    if (response.status !== 200) throw new Error(response.body.error?.message || "검증 기록을 읽을 수 없습니다.");
    if (!response.body.available) {
      $("verification-status").textContent = "미검증 · " + (response.body.message || "연결된 검증 기록이 없습니다.");
      log("저장된 검증 기록 미연결");
      return;
    }
    const verdict = response.body.verdict;
    const reasons = {
      STALE_INPUTS: "기준 입력이 변경되어 이전 결과의 재사용을 차단했습니다.",
      EXECUTION_FAILED: "실패한 실행 결과의 완료 처리를 차단했습니다.",
      NONPASS_CHECK: "실패·미검증 항목이 있어 완료 처리를 차단했습니다.",
      MISSING_AC: "필수 수용 기준의 검증이 빠졌습니다.",
      CHANGED_RESULTS: "실행 결과 파일이 변경됐습니다.",
      INVALID_ARTIFACT: "검증 자료를 확인해야 합니다.",
    };
    $("verification-status").textContent = verdict.status === "PASS"
      ? "PASS · " + verdict.checks + "개 확인 · P2 / D2 검증 범위와 현재 파일 일치"
      : "BLOCKED · " + verdict.reason + " · " + (reasons[verdict.reason] || "검증 자료를 확인하세요.");
    log("검증 기록 " + record.toUpperCase() + " · " + verdict.status);
  } catch (error) {
    if (version !== state.verificationVersion) return;
    $("verification-status").textContent = "확인 실패 · " + error.message;
  } finally {
    if (version === state.verificationVersion) $("verify").disabled = false;
  }
}

async function bootstrap() {
  $("boot-status").textContent = "로컬 API에 연결하고 있습니다.";
  try {
    const response = await api("/api/bootstrap");
    if (response.status !== 200 || !response.body.revisions?.p1 || !response.body.datasets?.raw) {
      throw new Error("데모 데이터를 읽을 수 없습니다.");
    }
    state.bootstrap = response.body;
    state.rows = clone(response.body.datasets.raw);
    renderRows();
    renderCompareRows("compare-raw", response.body.datasets.raw);
    renderCompareRows("compare-approved", response.body.datasets.approved);
    for (const id of ["calculate", "approve", "reject", "defer"]) $(id).disabled = false;
    $("boot-status").textContent = "";
    log("로컬 API 연결 · 합성 관측 3행 준비");
    const compare = await Promise.allSettled([
      api("/api/kpi/p1", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows: response.body.datasets.raw }) }),
      api("/api/kpi/p2", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows: response.body.datasets.approved }) }),
    ]);
    const values = [null, null];
    for (const [index, item] of compare.entries()) {
      const prefix = index === 0 ? "baseline" : "proposed";
      if (item.status === "fulfilled" && item.value.status === 200) {
        const result = item.value.body;
        $(prefix + "-value").textContent = number.format(result.kpi);
        $(prefix + "-detail").textContent = result.rows_used + "행 · 분자 " + result.numerator + " / 분모 " + result.denominator;
        values[index] = result.kpi;
      } else {
        $(prefix + "-detail").textContent = "API 계산 실패 · 연결을 확인하세요.";
      }
    }
    if (values.length === 2 && values.every((value) => Number.isFinite(value))) {
      const difference = values[1] - values[0];
      $("difference-value").textContent = (difference >= 0 ? "+" : "") + number.format(difference);
    }
  } catch (error) {
    $("boot-status").textContent = "연결 실패 · " + error.message + " ";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "secondary-button";
    retry.textContent = "다시 연결";
    retry.addEventListener("click", bootstrap);
    $("boot-status").append(retry);
  }
}

$("raw-data").addEventListener("click", () => selectDataset("raw"));
$("approved-data").addEventListener("click", () => selectDataset("approved"));
$("reset-data").addEventListener("click", () => selectDataset(state.dataset));
$("approve").addEventListener("click", () => decide("approved"));
$("reject").addEventListener("click", () => decide("rejected"));
$("defer").addEventListener("click", () => decide("pending"));
$("calculate").addEventListener("click", calculate);
$("verify").addEventListener("click", verifyRecord);
$("record").addEventListener("change", () => {
  state.verificationVersion += 1;
  $("verify").disabled = false;
  $("verification-status").textContent = "선택한 검증 기록을 확인하세요.";
});
$("theme").addEventListener("change", () => {
  if ($("theme").value === "neutral") delete document.documentElement.dataset.hkitBrand;
  else document.documentElement.dataset.hkitBrand = $("theme").value;
});
bootstrap();
