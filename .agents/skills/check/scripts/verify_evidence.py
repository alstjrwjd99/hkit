"""Check that executed verification results belong to the current inputs."""

import argparse
import hashlib
import json
from pathlib import Path


ROLES = {"prd", "contract", "data", "code", "tests"}


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def snapshot(context_path):
    context_path = Path(context_path).resolve()
    context = json.loads(context_path.read_text(encoding="utf-8"))
    if context.get("schema_version") != 1 or set(context.get("inputs", {})) != ROLES:
        raise ValueError("context requires schema_version 1 and prd/contract/data/code/tests inputs")
    required = context.get("required_ac")
    if not isinstance(required, list) or not required or any(not isinstance(ac, str) or not ac for ac in required):
        raise ValueError("required_ac must list the current mandatory acceptance criteria")
    if len(set(required)) != len(required):
        raise ValueError("duplicate required_ac")
    files = {}
    for role, paths in context["inputs"].items():
        if not isinstance(paths, list) or not paths:
            raise ValueError(f"{role} requires a nonempty list of files")
        entries = []
        for value in paths:
            if not isinstance(value, str) or not value:
                raise ValueError(f"{role} contains an invalid path")
            path = (context_path.parent / value).resolve()
            entries.append({"path": str(path), "sha256": digest(path)})
        if len({item["path"] for item in entries}) != len(entries):
            raise ValueError(f"{role} contains duplicate paths")
        files[role] = sorted(entries, key=lambda item: item["path"])
    return {"inputs": files, "required_ac": sorted(required)}


def write_evidence(path, scope_before_execution, result_path):
    path = Path(path)
    result_path = Path(result_path).resolve()
    evidence = {
        "schema_version": 1,
        "scope": scope_before_execution,
        "result": {"path": str(result_path), "sha256": digest(result_path)},
    }
    with path.open("x", encoding="utf-8") as output:
        json.dump(evidence, output, ensure_ascii=False, indent=2)
        output.write("\n")
    return evidence


def verify(context_path, evidence_path):
    evidence_path = Path(evidence_path).resolve()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("schema_version") != 1:
        return {"status": "BLOCKED", "reason": "UNSUPPORTED_EVIDENCE"}
    current = snapshot(context_path)
    if evidence.get("scope") != current:
        return {"status": "BLOCKED", "reason": "STALE_INPUTS"}
    result_ref = evidence.get("result", {})
    if not isinstance(result_ref.get("path"), str) or not result_ref["path"]:
        return {"status": "BLOCKED", "reason": "INVALID_RESULT_REFERENCE"}
    result_path = (evidence_path.parent / result_ref["path"]).resolve()
    if digest(result_path) != result_ref.get("sha256"):
        return {"status": "BLOCKED", "reason": "CHANGED_RESULTS"}
    result = json.loads(result_path.read_text(encoding="utf-8"))
    command = result.get("command")
    if not isinstance(command, list) or not command or any(not isinstance(part, str) for part in command):
        return {"status": "BLOCKED", "reason": "MISSING_COMMAND"}
    if type(result.get("returncode")) is not int or result["returncode"] != 0:
        return {"status": "BLOCKED", "reason": "EXECUTION_FAILED"}
    checks = result.get("checks")
    if not isinstance(checks, list) or not checks:
        return {"status": "BLOCKED", "reason": "NO_CHECKS"}
    ids = set()
    covered = set()
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("id"), str) or not check["id"]:
            return {"status": "BLOCKED", "reason": "INVALID_CHECK"}
        if check["id"] in ids:
            return {"status": "BLOCKED", "reason": "DUPLICATE_CHECK"}
        ids.add(check["id"])
        if check.get("status") != "PASS":
            return {"status": "BLOCKED", "reason": "NONPASS_CHECK"}
        ac_ids = check.get("ac_ids")
        if not isinstance(ac_ids, list) or any(not isinstance(ac, str) or not ac for ac in ac_ids):
            return {"status": "BLOCKED", "reason": "INVALID_AC_REFERENCE"}
        covered.update(ac_ids)
    missing = sorted(set(current["required_ac"]) - covered)
    if missing:
        return {"status": "BLOCKED", "reason": "MISSING_AC", "missing_ac": missing}
    return {"status": "PASS", "checks": len(checks), "required_ac": current["required_ac"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    try:
        verdict = verify(args.context, args.evidence)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        verdict = {"status": "BLOCKED", "reason": "INVALID_ARTIFACT", "detail": str(error)}
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
