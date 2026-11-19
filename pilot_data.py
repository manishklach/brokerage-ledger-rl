"""Synthetic spread task with disjoint train and evaluation underlyings."""

import json
import random
from decimal import Decimal


def cases(split, count):
    if split not in {"train", "eval"}:
        raise ValueError("Unknown split")
    rng = random.Random(31 if split == "train" else 97)
    roots = ("DEMOA", "DEMOB") if split == "train" else ("EVALX", "EVALY")
    for i in range(count):
        root = roots[i % len(roots)]
        side = rng.choice(["Put", "Call"])
        phase = rng.choice(["Open", "Close"])
        amount = rng.randint(1200, 25000)
        debit = rng.randint(100, 20000)
        strike = rng.randint(12, 200)
        quantity = rng.randint(1, 4)
        legs = [
            (root, "Jan", side, "Buy to " + phase, quantity, strike, -debit, True),
            (root, "Jan", side, "Sell to " + phase, quantity, strike + 5, amount, True),
            (root, "Feb", side, "Sell to " + phase, quantity, strike + 5, amount, False),
            (root, "Jan", side, "Buy to " + phase, quantity + 1, strike, -debit, False),
        ]
        rng.shuffle(legs)
        start = rng.randint(10, 100)
        lines, selected = [], []
        for n, (symbol, expiry, right, action, size, level, cash, target) in enumerate(legs, start):
            lines.append(f"{n} | {symbol} | {expiry} | {right} | {action} | {size} | {level} | {Decimal(cash).scaleb(-2):.2f}")
            if target:
                selected.append(n)
        expected_cash = f"{Decimal(amount - debit).scaleb(-2):.2f}"
        prompt = (
            f"Identify both legs of the {root} Jan {side} vertical ({phase.lower()}, {quantity} contracts). "
            "Add their signed net cash amounts. Return only a JSON object with source_lines (integer array) "
            "and net_cash (decimal string).\n"
            "Line | Underlying | Expiry | Right | Action | Quantity | Strike | Net cash\n"
            + "\n".join(lines)
        )
        yield {
            "question": prompt, "expected_lines": selected, "expected_cash": expected_cash,
            "answer": json.dumps({"source_lines": selected, "net_cash": expected_cash}),
        }
