"""Generate targeted Inkling lot-evidence training and validation splits."""

import argparse
import json
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from lot_pilot_data import classify, evidence_prompt

SCENARIOS = ("single_row_partial", "missing", "quantity_shortfall", "exact", "ambiguous")


def cases(split, count):
    seed, year = {"train": (715, 2036), "validation": (941, 2037)}[split]
    rng = random.Random(seed)
    for index in range(count):
        scenario = SCENARIOS[index % len(SCENARIOS)]
        first = date(year, 1, 1) + timedelta(days=rng.randrange(320))
        dates = [str(first + timedelta(days=offset)) for offset in rng.sample(range(15), rng.randint(1, 3))]
        requirements = {day: rng.randint(4, 24) for day in dates}
        target = rng.choice(dates)
        action, opposite = rng.sample(("Buy to Open", "Sell to Open"), 2)
        fills = []
        for day, quantity in requirements.items():
            sizes = [quantity]
            if day == target:
                if scenario == "single_row_partial":
                    sizes = [quantity + rng.randint(1, 9)]
                elif scenario == "missing":
                    sizes = []
                elif scenario == "quantity_shortfall":
                    sizes = [1, quantity - 2]
                elif scenario == "ambiguous":
                    sizes = [quantity, rng.randint(1, 9)]
                else:
                    sizes = [1, quantity - 1]
            fills.extend((day, action, size) for size in sizes)
            fills.append((day, opposite, quantity))
        unused = [str(first + timedelta(days=offset)) for offset in range(-6, 22)
                  if str(first + timedelta(days=offset)) not in requirements]
        for day in rng.sample(unused, rng.randint(5, 12)):
            fills.append((day, rng.choice((action, opposite)), rng.randint(1, 30)))
        rng.shuffle(fills)
        rows = [{"line": line, "date": day, "action": side, "quantity": size}
                for line, (day, side, size) in zip(rng.sample(range(10, 999), len(fills)), fills, strict=True)]
        status, lines = classify(requirements, rows, action)
        question = evidence_prompt(requirements, rows, action)
        if split == "validation":
            question = question.replace("Check the claimed opening allocation for",
                                        "Verify the broker's opening-date quantities for", 1)
        yield {
            "id": f"{split}-lot-{index+1:04d}", "scenario": scenario,
            "expected_cash": status, "expected_lines": lines, "question": question,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    splits = {split: list(cases(split, count))
              for split, count in (("train", 400), ("validation", 100))}
    with (args.output / "train.jsonl").open("w", encoding="utf-8") as output:
        for case in splits["train"]:
            answer = {"status": case["expected_cash"], "source_lines": case["expected_lines"]}
            messages = [{"role": "user", "content": case["question"]},
                        {"role": "assistant", "content": json.dumps(answer)}]
            output.write(json.dumps({"messages": messages}) + "\n")
    (args.output / "validation.json").write_text(
        json.dumps(splits["validation"], indent=2) + "\n", encoding="utf-8")
    print(json.dumps({split: Counter(case["scenario"] for case in rows)
                      for split, rows in splits.items()}, indent=2))


if __name__ == "__main__":
    main()
