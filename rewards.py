"""Binary reward for verified spread evidence and exact net cash."""

import json
from decimal import Decimal, InvalidOperation


def score_spread(completion: str, expected_lines: list[int], expected_cash: str) -> float:
    try:
        answer = json.loads(completion, object_pairs_hook=unique_fields)
        if not isinstance(answer, dict) or set(answer) != {"source_lines", "net_cash"}:
            return 0.0
        lines = answer["source_lines"]
        cash = answer["net_cash"]
        if not isinstance(lines, list) or any(type(line) is not int for line in lines):
            return 0.0
        if not isinstance(cash, str):
            return 0.0
        amount = Decimal(cash)
    except (ValueError, InvalidOperation):
        return 0.0
    return float(
        amount.is_finite()
        and amount == Decimal(expected_cash)
        and sorted(lines) == sorted(expected_lines)
    )


def unique_fields(pairs: list[tuple]) -> dict:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("Duplicate JSON fields")
    return fields
