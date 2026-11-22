"""Freeze broker-linked opening-evidence cases with explicit month and contract exclusions."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from hard_lot_holdout import build
from ledger import read_export
from option_lots import SETTLEMENT_ACTIONS
from period_review import read_schwab_realized
from reconcile import contract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transactions", type=Path)
    parser.add_argument("realized", type=Path)
    parser.add_argument("--months", nargs="+", required=True)
    parser.add_argument("--exclude-realized", nargs="*", type=Path, default=[])
    parser.add_argument("--exclude-cases", nargs="*", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    months = set(args.months)
    if len(months) != len(args.months) or "2026-10" in months:
        parser.error("Use distinct months outside the October 2026 benchmark")
    excluded = {
        row["instrument"] for row in read_schwab_realized(args.realized)
        if row["is_option"] and row["transaction_closed"][:7] not in months
    }
    for path in args.exclude_realized:
        excluded.update(row["instrument"] for row in read_schwab_realized(path) if row["is_option"])
    for path in args.exclude_cases:
        excluded.update(row["contract"] for row in json.loads(path.read_text(encoding="utf-8")))
    transactions = read_export(args.transactions)
    # The opening-evidence scorer does not account for inventory consumed by settlements.
    excluded.update(contract(row.symbol) for row in transactions if row.action in SETTLEMENT_ACTIONS)
    cases = list(build(transactions, args.realized, sorted(months), excluded))
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Holdout needs a nonempty set of unique case IDs")
    if excluded.intersection(case["contract"] for case in cases):
        raise ValueError("Holdout overlaps excluded contracts")
    content = json.dumps(cases, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        output.write(content)
    print(json.dumps({
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "cases": len(cases),
        "contracts": len({case["contract"] for case in cases}),
        "by_status": Counter(case["expected_status"] for case in cases),
        "by_month": Counter(case["month"] for case in cases),
        "multiple_opening_dates": sum(case["requested_dates"] > 1 for case in cases),
        "partial_open_rows": sum(case["partial_open_row"] for case in cases),
    }, indent=2))


if __name__ == "__main__":
    main()
