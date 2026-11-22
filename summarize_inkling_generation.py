"""Summarize matched stock and adapter replies from an Inkling generation run."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

VARIANTS = ("stock", "step12")


def summarize(rows):
    pairs = defaultdict(dict)
    for row in rows:
        variants = pairs[row["case"]]
        variant = row["variant"]
        if variant not in VARIANTS or variant in variants:
            raise ValueError("Unexpected or duplicate model variant")
        variants[variant] = row

    groups = {"supported": [], "unsupported": []}
    incomplete = 0
    for pair in pairs.values():
        if set(pair) != set(VARIANTS):
            incomplete += 1
            continue
        target = pair["stock"]["target"]
        if pair["step12"]["target"] != target:
            raise ValueError("Paired replies disagree on the expected status")
        groups["supported" if target == "supported" else "unsupported"].append(pair)

    result = {"incomplete_cases": incomplete, "groups": {}}
    for group, members in groups.items():
        total = len(members)
        both_exact = sum(all(pair[v]["correct"] for v in VARIANTS) for pair in members)
        stats = {"cases": total, "both_exact": both_exact,
                 "paired_accuracy": both_exact / total if total else None}
        for variant in VARIANTS:
            replies = [pair[variant] for pair in members]
            correct = sum(row["correct"] for row in replies)
            statuses = sorted({row["target"] for row in replies})
            stats[variant] = {
                "exact": correct,
                "accuracy": correct / total if total else None,
                "truncated": sum(row["truncated"] for row in replies),
                "status_recall": {
                    status: sum(row["predicted_status"] == status for row in replies if row["target"] == status)
                    / sum(row["target"] == status for row in replies)
                    for status in statuses
                },
            }
            if group == "unsupported":
                count = sum(row["predicted_status"] == "supported" for row in replies)
                stats[variant].update(false_supports=count, false_support_rate=count / total if total else None)
        result["groups"][group] = stats
    result["paired_accuracy"] = result["groups"]["supported"]["paired_accuracy"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replies", type=Path)
    args = parser.parse_args()
    with args.replies.open(encoding="utf-8") as source:
        result = summarize(json.loads(line) for line in source if line.strip())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
