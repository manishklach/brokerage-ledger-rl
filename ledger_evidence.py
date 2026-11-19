"""Enforce opening-evidence decisions and replay saved model replies offline."""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from lot_pilot_data import classify, score_lot

HEADER = "Line | Date | Action | Recorded quantity"


def recorded_claim(case):
    if "evidence_input" in case:
        evidence = case["evidence_input"]
        requirements = {day: Decimal(qty) for day, qty in evidence["required_by_date"].items()}
        rows = [{**row, "quantity": Decimal(row["quantity"])} for row in evidence["rows"]]
        return evidence["action"], requirements, rows

    # The first saved holdout stores input rows only in the rendered prompt.
    head, separator, body = case["question"].partition("\n" + HEADER + "\n")
    claim = re.fullmatch(r"Check the claimed opening allocation for (Buy to Open|Sell to Open): (.+)\.",
                         head.splitlines()[0])
    if not separator or not claim:
        raise ValueError("Unrecognized evidence prompt")
    requirements = {}
    for requested in claim[2].split(", "):
        qty, day = requested.split(" on ", 1)
        requirements[date.fromisoformat(day).isoformat()] = Decimal(qty)
    rows = []
    for line in body.splitlines():
        source, day, action, qty = line.split(" | ")
        rows.append({"line": int(source), "date": date.fromisoformat(day).isoformat(),
                     "action": action, "quantity": Decimal(qty)})
    return claim[1], requirements, rows


def decide(action, requirements, rows):
    if action not in {"Buy to Open", "Sell to Open"} or not requirements:
        raise ValueError("An opening action and requested dates are required")
    if any(not qty.is_finite() or qty <= 0 for qty in requirements.values()):
        raise ValueError("Requested quantities must be finite and positive")
    if any(not row["quantity"].is_finite() or row["quantity"] <= 0 for row in rows):
        raise ValueError("Opening row quantities must be finite and positive")
    if len({row["line"] for row in rows}) != len(rows):
        raise ValueError("Duplicate opening source rows")
    status, lines = classify(requirements, rows, action)
    matching = defaultdict(list)
    for row in rows:
        if row["action"] == action and row["date"] in requirements:
            matching[row["date"]].append(row)
    dates = {}
    for day, required in sorted(requirements.items()):
        matches = matching[day]
        recorded = sum((row["quantity"] for row in matches), Decimal(0))
        dates[day] = {
            "required": str(required),
            "recorded": str(recorded),
            "shortfall": str(max(Decimal(0), required - recorded)),
            "competing_rows": len(matches) > 1 and recorded > required,
            "matching_source_lines": sorted(row["line"] for row in matches),
        }
    return {"status": status, "source_lines": lines, "by_date": dates}


def replay(cases, replies):
    by_id = {row["id"]: row["reply"] for row in replies}
    ids = {case["id"] for case in cases}
    if len(ids) != len(cases) or len(by_id) != len(replies) or set(by_id) != ids:
        raise ValueError("Expected one saved reply per unique holdout case")
    details = []
    totals = Counter()
    by_status = defaultdict(Counter)
    for case in cases:
        expected = case["expected_status"]
        lines = case["expected_lines"]
        reply = by_id[case["id"]]
        decision = decide(*recorded_claim(case))
        answer = {key: decision[key] for key in ("status", "source_lines")}
        original = bool(score_lot(reply, lines, expected))
        enforced = bool(score_lot(json.dumps(answer), lines, expected))
        try:
            raw = json.loads(reply)
        except ValueError:
            raw = None
        false_support = expected == "missing_evidence" and isinstance(raw, dict) and raw.get("status") == "supported"
        enforced_false_support = expected == "missing_evidence" and decision["status"] == "supported"
        counts = {
            "cases": 1, "model_exact": int(original), "ledger_exact": int(enforced),
            "model_false_support": int(false_support),
            "ledger_false_support": int(enforced_false_support),
            "correct_model_answers_lost": int(original and not enforced),
        }
        totals.update(counts)
        by_status[expected].update(counts)
        details.append({"id": case["id"], "model_exact": original, "ledger_exact": enforced,
                        "model_false_support": false_support, "ledger": decision})
    return {"totals": totals, "by_status": by_status, "cases": details}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("scorecard", type=Path)
    parser.add_argument("--stage", default="sft")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    replies = json.loads(args.scorecard.read_text(encoding="utf-8"))[args.stage]["replies"]
    report = replay(cases, replies)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["totals"], sort_keys=True))


if __name__ == "__main__":
    main()
