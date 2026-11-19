"""Generate local prompts for the broker-requested opening-date evidence task."""

import argparse
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from ledger import read_export
from option_lots import match_options
from reconcile import contract


def build(rows, report, month):
    opens = defaultdict(list)
    closes = {item["close_line"]: item for item in match_options(rows, month)["closes"]}
    for row in rows:
        if row.action in {"Buy to Open", "Sell to Open"} and row.quantity:
            opens[contract(row.symbol)].append(row)

    for group in report["groups"]:
        clean = (group["status"] == "group_ties"
                 and len(group["transaction_lines"]) == len(group["broker_lines"]) == 1)
        if not clean and group["status"] != "opening_date_quantity_difference":
            continue
        close = closes[group["transaction_lines"][0]]
        intended = {"Buy to Open" if closes[line]["close_action"] == "Sell to Close" else "Sell to Open"
                    for line in group["transaction_lines"]}
        if len(intended) != 1:
            continue
        action, = intended
        requirements = {day: Decimal(qty) for day, qty in group["broker_quantity_by_open_date"].items()}
        rows_for_prompt = sorted(
            (row for row in opens[group["contract"]]
             if row.effective_date.isoformat() <= group["closed"]),
            key=lambda row: row.source_line,
        )
        available = defaultdict(Decimal)
        selected = []
        for row in rows_for_prompt:
            day = row.effective_date.isoformat()
            if row.action == action and day in requirements:
                available[day] += abs(row.quantity)
                selected.append(row.source_line)
        supported = all(available[day] >= qty for day, qty in requirements.items())
        if supported != clean:
            continue
        demand = ", ".join(f"{qty} on {day}" for day, qty in sorted(requirements.items()))
        prompt = (
            f"Verify whether these recorded opening rows support {demand} with action {action}. "
            "Sum the quantities of rows matching the exact date and action for each requested date. "
            "If every date has enough, return supported and all matching source lines. "
            "Otherwise return missing_evidence and an empty list. "
            "Return only JSON with status and source_lines.\n"
            "Line | Date | Action | Recorded quantity\n"
            + "\n".join(f"{row.source_line} | {row.effective_date} | {row.action} | {abs(row.quantity)}"
                        for row in rows_for_prompt)
        )
        yield {
            "id": f"close-{close['close_line']}",
            "question": prompt,
            "expected_status": "supported" if supported else "missing_evidence",
            "expected_lines": selected if supported else [],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transactions", type=Path)
    parser.add_argument("reconciliation", type=Path)
    parser.add_argument("--month", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.reconciliation.read_text(encoding="utf-8"))["realized"]
    cases = list(build(read_export(args.transactions), report, args.month))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
