"""Build and score a local natural-language close-selection benchmark."""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from ledger_evidence import decide, recorded_claim
from rewards import unique_fields

CHECK = "check_opening_evidence"
ACTIONS = {CHECK, "clarify", "no_match"}


def option_name(symbol):
    root, expiry, strike, right = symbol.split()
    return f"{root} {strike} {'call' if right == 'C' else 'put'} expiring {expiry}"


def close_metadata(case):
    opening, _, _ = recorded_claim(case)
    side = "Sell to Close" if opening == "Buy to Open" else "Buy to Close"
    return {"close_id": case["id"], "contract": case["contract"], "month": case["month"], "action": side}


def prompt(question, candidates):
    listing = "\n".join(
        f"{r['close_id']} | {r['contract']} | {r['month']} | {r['action']}" for r in candidates
    )
    return (
        "Route the user's request using only these candidate closes. Match the requested contract "
        "and any stated month, closing action, or source line. If one close fits, select "
        "check_opening_evidence and its close_id. If several fit, select clarify. If none fit, "
        "select no_match. For clarify or no_match use null for close_id. "
        "Return only JSON with operation and close_id. The ledger obtains the opening dates and quantities.\n"
        "Close ID | Contract (ticker expiry strike C/P) | Posted month | Action\n"
        + listing + "\nUser: " + question
    )


def build(cases):
    rng = random.Random(919)
    metadata = [close_metadata(case) for case in cases]
    groups = defaultdict(list)
    for row in metadata:
        groups[row["contract"]].append(row)
    single = [rows[0] for rows in groups.values() if len(rows) == 1]
    repeated = [rows for rows in groups.values() if len(rows) > 1]
    if len(single) < 18 or len(repeated) < 8:
        raise ValueError("Need 18 unique contracts and eight contracts with repeated closes")
    result = []

    def add(question, matches, operation, close_id, preferred_month=None):
        excluded = {r["contract"] for r in matches}
        others = [r for r in metadata if r["contract"] not in excluded]
        rng.shuffle(others)
        same_month = [r for r in others if r["month"] == preferred_month]
        distractors = (same_month or others)[:max(2, 6 - len(matches))]
        candidates = matches + distractors
        rng.shuffle(candidates)
        result.append({
            "id": f"query-{len(result) + 1:02d}", "question": prompt(question, candidates),
            "candidates": candidates, "expected_status": operation, "expected_close_id": close_id,
        })

    patterns = [
        "Can the opening fills back up my {option} close in {month}?",
        "For the {option}, verify whether the {month} exit has enough opening history.",
        "Check the trade I closed in {month}, the {option}. Do we have evidence for the opening lot?",
        "Look at source line {line} for my {option}. Can you verify the opening evidence?",
        "Did we record enough opening quantity for the {option} I closed in {month}?",
        "Does the record support the opening allocation for the {month} close on my {option}?",
    ]
    for index, row in enumerate(rng.sample(single, 18)):
        question = patterns[index % len(patterns)].format(
            option=option_name(row["contract"]), month=row["month"], line=row["close_id"].split("-")[-1],
        )
        add(question, [row], CHECK, row["close_id"], row["month"])
    for group in rng.sample(repeated, 8):
        add(f"Can you check the opening evidence for the close on my {option_name(group[0]['contract'])}?",
            group, "clarify", None)
    for row in rng.sample(single, 4):
        add(f"Check whether my February 2026 close on the {option_name(row['contract'])} has opening evidence.",
            [row], "no_match", None, row["month"])
    rng.shuffle(result)
    return result


def parse_query(reply):
    try:
        answer = json.loads(reply, object_pairs_hook=unique_fields)
    except ValueError:
        answer = None
    valid = (
        isinstance(answer, dict) and set(answer) == {"operation", "close_id"}
        and isinstance(answer["operation"], str) and answer["operation"] in ACTIONS
        and (answer["close_id"] is None or isinstance(answer["close_id"], str))
    )
    return answer if valid else None


def query_score(reply, case):
    answer = parse_query(reply)
    operation = answer is not None and answer["operation"] == case["expected_status"]
    close_id = answer is not None and answer["close_id"] == case["expected_close_id"]
    return {"valid_json": answer is not None, "operation": operation, "close_id": close_id,
            "exact": operation and close_id}


def execute_query(reply, candidates, evidence_by_id):
    answer = parse_query(reply)
    if answer is None:
        return {"operation": "invalid_query"}
    operation, close_id = answer["operation"], answer["close_id"]
    if operation != CHECK:
        return {"operation": operation if close_id is None else "invalid_query"}
    if close_id not in {row["close_id"] for row in candidates} or close_id not in evidence_by_id:
        return {"operation": "invalid_query"}
    return {"operation": operation, "close_id": close_id,
            "ledger": decide(*recorded_claim(evidence_by_id[close_id]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("holdout", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence_cases = json.loads(args.holdout.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in evidence_cases}
    cases = build(evidence_cases)
    for case in cases:
        if case["expected_status"] == CHECK:
            case["expected_ledger"] = decide(*recorded_claim(by_id[case["expected_close_id"]]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
