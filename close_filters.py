"""Resolve model-extracted close filters against a local evidence index."""

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from ledger_evidence import decide, recorded_claim
from rewards import unique_fields

KEYS = ("ticker", "expiry", "strike", "right", "month", "source_line")
FILTER_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        key: {"type": ["integer", "null"] if key == "source_line" else ["string", "null"]}
        for key in KEYS
    },
    "required": list(KEYS),
    "additionalProperties": False,
})


def extraction_prompt(question):
    return (
        "Extract only filters explicitly stated in the user's question. Return one JSON object "
        "with ticker, expiry, strike, right, month, and source_line. Use null for an omitted field. "
        "Ticker is uppercase. Expiry is the option expiration YYYY-MM-DD. Strike is a decimal string. "
        "Right is C for call or P for put. Month is the month the position closed, YYYY-MM, "
        "and must not be inferred from expiration. Source_line is an integer if specified.\n"
        f"User: {question}"
    )


def parse_filters(reply):
    try:
        filters = json.loads(reply, object_pairs_hook=unique_fields)
        if not isinstance(filters, dict) or set(filters) != set(KEYS):
            return None
        for name in KEYS[:-1]:
            if filters[name] is not None and not isinstance(filters[name], str):
                return None
        line = filters["source_line"]
        if line is not None and (type(line) is not int or line <= 0):
            return None
        if filters["ticker"] is not None:
            filters["ticker"] = filters["ticker"].upper()
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9./^-]*", filters["ticker"]):
                return None
        if filters["right"] not in (None, "C", "P"):
            return None
        expiry, month, strike = (filters[key] for key in ("expiry", "month", "strike"))
        if expiry is not None and date.fromisoformat(expiry).isoformat() != expiry:
            return None
        if month is not None and date.fromisoformat(month + "-01").isoformat() != month + "-01":
            return None
        if strike is not None:
            if not re.fullmatch(r"\d+(?:\.\d+)?", strike) or Decimal(strike) <= 0:
                return None
            filters["strike"] = format(Decimal(strike).normalize(), "f")
        return filters if any(value is not None for value in filters.values()) else None
    except (ValueError, InvalidOperation):
        return None


def resolve(reply, evidence_cases):
    filters = parse_filters(reply)
    if filters is None:
        return {"operation": "invalid_filters"}
    matches = []
    for case in evidence_cases:
        ticker, expiry, strike, right = case["contract"].split()
        by_field = {"ticker": ticker, "expiry": expiry, "strike": strike,
                    "right": right, "month": case["month"]}
        if any(filters[key] is not None and filters[key] != value for key, value in by_field.items()):
            continue
        if filters["source_line"] is not None and filters["source_line"] not in case["close_lines"]:
            continue
        matches.append(case)
    if not matches:
        return {"operation": "no_match"}
    if len(matches) > 1:
        return {"operation": "clarify", "close_ids": [case["id"] for case in matches]}
    case, = matches
    return {"operation": "check_opening_evidence", "close_id": case["id"],
            "ledger": decide(*recorded_claim(case))}
