"""Small contract-driven HTTP backend for the PRD/EDA integration example."""

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, DecimalException, localcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json


FIELDS = {"observation_id", "route", "day", "demand", "wait_minutes"}
FORMULA = "sum(demand * wait_minutes) / sum(demand)"
RULES = {"required", "type", "range", "date_format", "unique"}


def number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Expected a finite number")
    try:
        result = Decimal(str(value))
    except DecimalException as error:
        raise ValueError("Expected a finite number") from error
    if not result.is_finite():
        raise ValueError("Expected a finite number")
    return result


def parsed_date(value, fmt):
    if not isinstance(value, str):
        raise ValueError("Expected a date string")
    if fmt == "iso8601":
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    return datetime.strptime(value, fmt).date()


def configuration(prd, contract):
    if type(contract.get("schema_version")) is not int or contract["schema_version"] != 1 or contract.get("status") != "confirmed":
        raise ValueError("A confirmed schema version 1 contract is required")
    if not isinstance(contract.get("revision"), str) or not contract["revision"]:
        raise ValueError("The contract revision is required")
    if not isinstance(prd.get("revision"), str) or not prd["revision"] or contract.get("prd_revision") != prd["revision"]:
        raise ValueError("The contract must reference the current PRD")
    if prd.get("kpi", {}).get("formula") != FORMULA:
        raise ValueError("Unsupported KPI formula")
    try:
        start = date.fromisoformat(prd["period"]["start"])
        end = date.fromisoformat(prd["period"]["end"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("A valid PRD period is required") from error
    if start > end:
        raise ValueError("The PRD period is reversed")
    constraints = contract.get("constraints")
    if not isinstance(constraints, list):
        raise ValueError("Contract constraints must be a list")
    active = []
    identifiers = set()
    for rule in constraints:
        if not isinstance(rule, dict) or rule.get("status") not in {"confirmed", "proposed"}:
            raise ValueError("Each constraint must have a supported status")
        if rule["status"] == "proposed":
            continue
        columns = rule.get("columns")
        kind = rule.get("rule")
        parameters = rule.get("parameters")
        if not isinstance(kind, str) or kind not in RULES:
            raise ValueError("Unsupported confirmed rule")
        if (not isinstance(columns, list) or not columns
                or any(not isinstance(column, str) or column not in FIELDS for column in columns)
                or len(set(columns)) != len(columns)):
            raise ValueError("Unsupported constraint columns")
        if kind != "unique" and len(columns) != 1:
            raise ValueError("This constraint requires one column")
        if not isinstance(parameters, dict):
            raise ValueError("Constraint parameters must be an object")
        identifier = rule.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("Confirmed constraint IDs must be distinct")
        identifiers.add(identifier)
        for field in ("ac_ids", "evidence"):
            entries = rule.get(field)
            if not isinstance(entries, list) or not entries or any(
                not isinstance(entry, str) or not entry for entry in entries
            ):
                raise ValueError("Confirmed constraints require AC and evidence references")
        if not set(rule["ac_ids"]).issubset(prd.get("required_ac", [])):
            raise ValueError("A constraint references an unknown AC")
        if kind == "type" and parameters.get("type") not in {"integer", "number", "boolean", "string"}:
            raise ValueError("Unsupported data type")
        if kind == "range":
            if not parameters or set(parameters).difference({"min", "max"}):
                raise ValueError("A range requires min or max")
            for value in parameters.values():
                number(value)
            if "min" in parameters and "max" in parameters:
                if number(parameters["min"]) > number(parameters["max"]):
                    raise ValueError("The constraint range is reversed")
        if kind == "date_format":
            fmt = parameters.get("format")
            if not isinstance(fmt, str) or not fmt:
                raise ValueError("A date format is required")
            if fmt != "iso8601":
                try:
                    sample = date(2026, 11, 1).strftime(fmt)
                    parsed_date(sample, fmt)
                except (ValueError, TypeError) as error:
                    raise ValueError("Unsupported date format") from error
        active.append(rule)
    policy = prd.get("input_policy", {}).get("duplicates")
    if policy not in {"count_all", "reject"}:
        raise ValueError("Unsupported duplicate policy")
    has_identity_rule = any(
        rule["rule"] == "unique" and rule["columns"] == ["observation_id"] for rule in active
    )
    if has_identity_rule != (policy == "reject"):
        raise ValueError("The contract and PRD duplicate policies disagree")
    return active, start, end


def validate(rows, constraints, start, end):
    if not rows:
        raise ValueError("At least one row is required")
    for rule in constraints:
        columns = rule["columns"]
        column = columns[0]
        parameters = rule["parameters"]
        kind = rule["rule"]
        seen = set()
        for row in rows:
            value = row.get(column)
            if kind == "required":
                if value is None or isinstance(value, str) and not value.strip():
                    raise ValueError(f"{column} is required")
                continue
            if value is None:
                continue
            if kind == "type":
                data_type = parameters["type"]
                if data_type in {"integer", "number"}:
                    converted = number(value)
                    if data_type == "integer" and converted != converted.to_integral_value():
                        raise ValueError(f"{column} must be an integer")
                elif data_type == "string" and not isinstance(value, str):
                    raise ValueError(f"{column} must be a string")
                elif data_type == "boolean" and not (
                    isinstance(value, bool)
                    or isinstance(value, str) and value.lower() in {"true", "false"}
                ):
                    raise ValueError(f"{column} must be boolean")
            elif kind == "range":
                converted = number(value)
                if "min" in parameters and converted < number(parameters["min"]):
                    raise ValueError(f"{column} is below its minimum")
                if "max" in parameters and converted > number(parameters["max"]):
                    raise ValueError(f"{column} is above its maximum")
            elif kind == "date_format":
                parsed_date(value, parameters["format"])
            elif kind == "unique":
                key = tuple(row.get(name) for name in columns)
                if any(item is None or isinstance(item, str) and not item.strip() for item in key):
                    continue
                try:
                    if key in seen:
                        raise ValueError("Duplicate observation key")
                    seen.add(key)
                except TypeError as error:
                    raise ValueError("Key values must be scalar") from error
    day_format = next(
        (rule["parameters"]["format"] for rule in constraints
         if rule["rule"] == "date_format" and rule["columns"] == ["day"]),
        "iso8601",
    )
    normalized = []
    for row in rows:
        current = parsed_date(row.get("day"), day_format)
        if not start <= current <= end:
            raise ValueError("The observation is outside the PRD period")
        normalized.append((number(row.get("demand")), number(row.get("wait_minutes"))))
    return normalized


def json_number(value):
    if value == value.to_integral_value():
        return int(value)
    result = float(value)
    if not Decimal(str(result)).is_finite():
        raise ValueError("The result exceeds the JSON numeric range")
    return result


def make_handler(prd, contract):
    """Build the contract-driven request handler for this example."""
    prd, contract = deepcopy(prd), deepcopy(contract)
    constraints, start, end = configuration(prd, contract)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, body):
            encoded = json.dumps(body, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def error(self, status, code, message):
            self.respond(status, {"error": {"code": code, "message": message}})

        def do_GET(self):
            self.error(404, "not_found", "Unknown endpoint")

        def do_POST(self):
            if self.path != "/kpi":
                self.error(404, "not_found", "Unknown endpoint")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1_048_576:
                    raise ValueError("A JSON body up to 1 MiB is required")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
                    raise ValueError("Expected an object with a rows array")
                rows = payload["rows"]
                if any(not isinstance(row, dict) for row in rows):
                    raise ValueError("Every row must be an object")
            except (ValueError, UnicodeError) as error:
                self.error(400, "invalid_request", str(error))
                return
            try:
                values = validate(rows, constraints, start, end)
                precision = 28 + sum(len(value.as_tuple().digits) for pair in values for value in pair)
                with localcontext() as context:
                    context.prec = precision
                    numerator = sum((demand * wait for demand, wait in values), Decimal(0))
                    denominator = sum((demand for demand, wait in values), Decimal(0))
                    if not denominator:
                        raise ValueError("The KPI denominator is zero")
                    result = {
                        "kpi": json_number(numerator / denominator),
                        "numerator": json_number(numerator),
                        "denominator": json_number(denominator),
                        "rows_used": len(rows),
                        "prd_revision": prd["revision"],
                        "contract_revision": contract["revision"],
                    }
                self.respond(200, result)
            except (ValueError, TypeError, DecimalException, OverflowError) as error:
                self.error(422, "validation_error", str(error))

    return Handler


def make_server(prd, contract):
    """Return an unstarted, loopback-only HTTP server for this example."""
    return ThreadingHTTPServer(("127.0.0.1", 0), make_handler(prd, contract))
