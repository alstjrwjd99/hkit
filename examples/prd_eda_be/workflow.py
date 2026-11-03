"""Decision transition used by the synthetic integration exercise."""

from copy import deepcopy


def apply_decision(prd, contract, proposed_prd, proposed_contract, decision):
    state = decision.get("state")
    if state not in {"approved", "rejected", "pending"}:
        raise ValueError("Unknown decision state")
    if state != "approved":
        return deepcopy(prd), deepcopy(contract)
    if not decision.get("actor") or not decision.get("id"):
        raise ValueError("An attributable decision is required")
    if decision.get("from_prd") != prd["revision"] or decision.get("to_prd") != proposed_prd["revision"]:
        raise ValueError("The decision does not apply to these PRD revisions")
    if proposed_contract["prd_revision"] != proposed_prd["revision"]:
        raise ValueError("The proposed contract belongs to another PRD")
    updated_prd = deepcopy(proposed_prd)
    updated_prd["decision_id"] = decision["id"]
    updated_contract = deepcopy(proposed_contract)
    updated_contract["status"] = "confirmed"
    for constraint in updated_contract["constraints"]:
        constraint["status"] = "confirmed"
    return updated_prd, updated_contract
