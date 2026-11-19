"""Synthetic opening-lot evidence task and exact executable reward."""

import json
import random
from collections import defaultdict

from rewards import unique_fields


def score_lot(reply, expected_lines, expected_cash):
    try:
        answer = json.loads(reply, object_pairs_hook=unique_fields)
    except ValueError:
        return 0.0
    if not isinstance(answer, dict) or set(answer) != {"status", "source_lines"}:
        return 0.0
    lines = answer["source_lines"]
    if not isinstance(lines, list) or any(type(x) is not int for x in lines):
        return 0.0
    return float(answer["status"] == expected_cash and sorted(lines) == sorted(expected_lines))


def lot_cases(split, count):
    rng = random.Random({"train": 331, "eval": 997}[split])
    for index in range(count):
        needed = rng.randint(2, 20)
        day = rng.randint(5, 20)
        target_side = rng.choice(("Buy to Open", "Sell to Open"))
        other_side = "Sell to Open" if target_side == "Buy to Open" else "Buy to Open"
        mode = index % 4
        target_sizes = ([needed] if mode == 0 else [1, needed - 1] if mode == 1
                        else [needed - 1] if mode == 2 else [])
        rows = [(day, target_side, size, True) for size in target_sizes]
        rows.extend([
            (day - 1, target_side, needed, False),
            (day, other_side, needed, False),
            (day + 1, target_side, needed, False),
        ])
        rng.shuffle(rows)
        lines = rng.sample(range(10, 130), len(rows))
        supported = mode < 2
        selected = sorted(line for line, row in zip(lines, rows) if row[3]) if supported else []
        status = "supported" if supported else "missing_evidence"
        month = "2026-03" if split == "train" else "2026-08"
        question = (
            f"Verify whether these available opening rows support {needed} contracts "
            f"with action {target_side} on {month}-{day:02d}. "
            "Use only rows with that action and date. If their quantities total at least "
            "the requested quantity, return supported and all matching source lines. "
            "Otherwise return missing_evidence and an empty list. "
            "Return only JSON with status and source_lines.\n"
            "Line | Date | Action | Available quantity\n"
            + "\n".join(f"{line} | {month}-{d:02d} | {action} | {qty}"
                        for line, (d, action, qty, _) in zip(lines, rows))
        )
        yield {"question": question, "expected_lines": selected, "expected_cash": status,
               "answer": json.dumps({"status": status, "source_lines": selected})}


def classify(requirements, rows, action):
    matching = defaultdict(list)
    for row in rows:
        day = row["date"]
        if day in requirements and row["action"] == action:
            matching[day].append(row)
    totals = {
        day: sum(row["quantity"] for row in matching[day]) for day in requirements
    }
    if any(totals[day] < required for day, required in requirements.items()):
        return "missing_evidence", []
    if any(totals[day] > required and len(matching[day]) > 1
           for day, required in requirements.items()):
        return "ambiguous", []
    return "supported", sorted(row["line"] for group in matching.values() for row in group)


def evidence_prompt(requirements, rows, action):
    demand = ", ".join(f"{quantity} on {day}" for day, quantity in sorted(requirements.items()))
    evidence = "\n".join(f"{row['line']} | {row['date']} | {row['action']} | {row['quantity']}" for row in rows)
    return (
        f"Check the claimed opening allocation for {action}: {demand}.\n"
        "Compare only matching dates and actions. If any requested date has too little quantity, "
        "return missing_evidence. Otherwise, if any date has multiple matching rows whose "
        "combined quantity exceeds the request, return ambiguous. Otherwise return supported "
        "and all matching row IDs. Return only JSON with status and source_lines. For "
        "missing_evidence or ambiguous, source_lines must be empty.\n"
        "Line | Date | Action | Recorded quantity\n" + evidence
    )


def hard_lot_cases(split, count):
    rng = random.Random({"train": 722, "eval": 409}[split])
    month = "2030-05" if split == "train" else "2031-08"
    for index in range(count):
        day = rng.randint(4, 18)
        dates = [f"{month}-{day + offset:02d}" for offset in (0, 2)]
        requirements = {date: rng.randint(2, 16) for date in dates}
        action = rng.choice(("Buy to Open", "Sell to Open"))
        opposite = "Sell to Open" if action == "Buy to Open" else "Buy to Open"
        scenario = index % 3
        target = rng.choice(dates)
        rows = []

        def add(date, side, quantity):
            rows.append({"date": date, "action": side, "quantity": quantity})

        for date, quantity in requirements.items():
            if date == target and scenario == 0:
                add(date, action, quantity - 1)
            elif date == target and scenario == 1:
                add(date, action, quantity)
                add(date, action, rng.randint(1, 4))
            elif rng.choice((True, False)):
                part = rng.randrange(1, quantity)
                add(date, action, part)
                add(date, action, quantity - part)
            else:
                add(date, action, quantity + rng.randint(0, 3))
            add(date, opposite, quantity)
        add(f"{month}-{day - 1:02d}", action, max(requirements.values()))
        rng.shuffle(rows)
        for line, row in zip(rng.sample(range(100, 999), len(rows)), rows, strict=True):
            row["line"] = line
        status, lines = classify(requirements, rows, action)
        yield {
            "question": evidence_prompt(requirements, rows, action),
            "expected_lines": lines, "expected_cash": status,
            "answer": json.dumps({"status": status, "source_lines": lines}),
        }
