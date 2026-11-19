"""Synthetic opening-lot evidence task and exact executable reward."""

import json
import random

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
