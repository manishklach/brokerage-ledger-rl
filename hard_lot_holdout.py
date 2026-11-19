"""Build a fresh, broker-backed holdout for opening evidence and ambiguity."""

import argparse
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from ledger import read_export
from lot_pilot_data import classify, evidence_prompt
from reconcile import contract, realized_comparison

OPEN_FOR_CLOSE = {"Sell to Close": "Buy to Open", "Buy to Close": "Sell to Open"}


def build(rows, realized, months, excluded_contracts):
    by_line = {row.source_line: row for row in rows}
    opens = defaultdict(list)
    for row in rows:
        if row.action in OPEN_FOR_CLOSE.values() and row.quantity:
            opens[contract(row.symbol)].append(row)
    for month in months:
        for group in realized_comparison(rows, realized, month)["groups"]:
            symbol = group["contract"]
            if symbol in excluded_contracts or not group["broker_lines"]:
                continue
            trade_lines = group["transaction_lines"]
            directions = {OPEN_FOR_CLOSE[by_line[line].action] for line in trade_lines}
            if len(directions) != 1:
                continue
            action, = directions
            requirements = {day: Decimal(qty) for day, qty in group["broker_quantity_by_open_date"].items()}
            evidence = [
                {"line": row.source_line, "date": row.effective_date.isoformat(),
                 "action": row.action, "quantity": abs(row.quantity)}
                for row in sorted(opens[symbol], key=lambda item: item.source_line)
                if (row.effective_date.isoformat(), -row.source_line) <= (group["closed"], -min(trade_lines))
            ]
            status, lines = classify(requirements, evidence, action)
            yield {
                "id": f"close-{min(trade_lines)}", "month": month, "contract": symbol,
                "question": evidence_prompt(requirements, evidence, action),
                "expected_status": status, "expected_lines": lines,
                "broker_lines": group["broker_lines"], "close_lines": trade_lines,
                "partial_open_row": status == "supported" and any(
                    row["line"] in lines and row["quantity"] > requirements[row["date"]] for row in evidence
                ),
                "requested_dates": len(requirements), "source_open_rows": len(evidence),
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transactions", type=Path)
    parser.add_argument("realized", type=Path)
    parser.add_argument("--months", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(set(args.months)) != len(args.months) or "2026-10" in args.months:
        parser.error("Use distinct months outside the October 2026 benchmark")
    rows = read_export(args.transactions)
    october = realized_comparison(rows, args.realized, "2026-10")
    excluded = {group["contract"] for group in october["groups"]}
    cases = list(build(rows, args.realized, args.months, excluded))
    if len(cases) != len({case["id"] for case in cases}):
        raise ValueError("Duplicate holdout case IDs")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
