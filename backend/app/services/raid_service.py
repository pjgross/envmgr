"""RAID service — scoring + status-transition helpers (pure) plus (later) CRUD."""
from typing import Optional

# Allowed status transitions per item_type. `promoted` (risk) is a terminal
# state set only by the promotion action, not by ordinary transitions.
_TRANSITIONS: dict[str, dict[str, list[str]]] = {
    "risk": {
        "open": ["mitigating", "closed"],
        "mitigating": ["closed", "open"],
        "closed": [],
        "promoted": [],
    },
    "assumption": {
        "open": ["closed"],
        "closed": ["open"],
    },
    "issue": {
        "open": ["in_progress", "closed"],
        "in_progress": ["resolved", "open"],
        "resolved": ["closed", "in_progress"],
        "closed": [],
    },
    "dependency": {
        "identified": ["in_progress", "closed"],
        "in_progress": ["met", "closed"],
        "met": ["closed"],
        "closed": [],
    },
}


def severity(probability: Optional[int], impact: Optional[int]) -> Optional[int]:
    """probability x impact, or None if either factor is unset."""
    if probability is None or impact is None:
        return None
    return probability * impact


def rag(sev: Optional[int], config: dict) -> Optional[str]:
    """Map a severity score to a RAG band label using the tenant config bands."""
    if sev is None:
        return None
    for band in config.get("rag_bands", []):
        if band["min"] <= sev <= band["max"]:
            return band["rag"]
    return None


def is_transition_allowed(item_type: str, from_status: str, to_status: str) -> bool:
    """True if the status change is permitted for this item_type (same-state ok)."""
    if from_status == to_status:
        return True
    return to_status in _TRANSITIONS.get(item_type, {}).get(from_status, [])
