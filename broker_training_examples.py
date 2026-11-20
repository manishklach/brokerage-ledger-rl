"""Produce redacted training examples from a private broker-lot reconciliation."""

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

OPEN_LINKS = {"quantity_match", "single_row_partial"}


def make_examples(lots):
    splits = {"train": [], "eval": []}
    for index, lot in enumerate(lots):
        digest = hashlib.sha256(lot["instrument"].encode()).digest()
        split = "eval" if int.from_bytes(digest[:2], "big") % 5 == 0 else "train"
        rng = random.Random(48021 + index)
        broker, opening, closing = rng.sample(range(11, 100), 3)
        open_evidence, close_evidence = lot["open_evidence"], lot["close_evidence"]
        close_linked = close_evidence["status"] == "quantity_match"
        open_linked = open_evidence["status"] in OPEN_LINKS
        close_label = {
            "quantity_match": "same contract, date and quantity; one event action",
            "unresolved": "same contract and date but quantity or event action differs",
            "missing": "no matching close transaction group",
        }[close_evidence["status"]]
        open_label = {
            "quantity_match": "same contract, date, side and sufficient quantity; group total matches",
            "single_row_partial": "same contract, date and side; one row covers a partial allocation",
            "missing": "no matching opening transaction rows",
            "predates_export": "opening date predates the transaction export",
            "quantity_shortfall": "opening rows cannot cover the broker allocation",
            "ambiguous": "multiple possible opening row allocations",
            "direction_unresolved": "opening direction cannot be established",
        }[open_evidence["status"]]
        records = [
            f"{broker}: broker realized lot with reported opening and closing allocation",
            f"{opening}: opening transaction evidence: {open_label}",
            f"{closing}: closing transaction evidence: {close_label}",
        ]
        rng.shuffle(records)
        status, lines = "unresolved", [broker]
        if close_linked:
            status, lines = "close_only", [broker, closing]
        if close_linked and open_linked:
            status, lines = "both_linked", [broker, opening, closing]
        question = (
            "Review the broker-reported lot and separate it from corroborating transaction evidence. "
            "Return JSON with status and source_lines. Cite the broker row in all cases. "
            "If closing evidence is not verified, use unresolved and cite only the broker row. "
            "If the close is verified but the opening is not, use close_only and cite the broker and close. "
            "If both are verified, including a single opening row that covers a partial allocation, "
            "use both_linked and cite all three.\n" + "\n".join(records)
        )
        splits[split].append({
            "question": question, "expected_lines": sorted(lines), "expected_cash": status,
            "answer": json.dumps({"status": status, "source_lines": sorted(lines)}),
        })
    for split in splits.values():
        random.Random(81039).shuffle(split)
    return splits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lots = json.loads(args.review.read_text(encoding="utf-8"))["broker_lots"]
    splits = make_examples(lots)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(splits, indent=2) + "\n", encoding="utf-8")
    print({split: dict(Counter(row["expected_cash"] for row in rows)) for split, rows in splits.items()})


if __name__ == "__main__":
    main()
