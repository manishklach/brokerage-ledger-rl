"""Review a local Schwab transaction year against broker-reported realized lots."""

import argparse
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from ledger import cash_total, number, parse_date, read_export
from reconcile import contract, export_rows, realized_comparison

FIELDS = {
    "Symbol", "Closed Date", "Opened Date", "Proceeds", "Cost Basis (CB)",
    "Gain/Loss ($)", "Long Term Gain/Loss", "Short Term Gain/Loss", "Term",
    "Wash Sale?", "Disallowed Loss",
}


def review(transactions, realized_path, year):
    prefix = str(year)
    first_posted = min(row.posted_date for row in transactions)
    first_effective = min(row.effective_date for row in transactions)
    last_posted = max(row.posted_date for row in transactions)
    totals = defaultdict(lambda: defaultdict(Decimal))
    details = []
    issues = defaultdict(list)
    for line, row in export_rows(realized_path, FIELDS):
        closed = parse_date(row["Closed Date"])
        if closed.year != year:
            continue
        opened = parse_date(row["Opened Date"])
        option = contract(row["Symbol"])
        underlying = option.split()[0] if option else row["Symbol"]
        amounts = {
            "proceeds": number(row["Proceeds"]), "broker_basis": number(row["Cost Basis (CB)"]),
            "realized": number(row["Gain/Loss ($)"]),
            "short_term": number(row["Short Term Gain/Loss"]) or Decimal(0),
            "long_term": number(row["Long Term Gain/Loss"]) or Decimal(0),
            "disallowed_loss_reported": number(row["Disallowed Loss"]) or Decimal(0),
        }
        if any(value is None for value in amounts.values()):
            raise ValueError(f"Missing realized dollars on broker source line {line}")
        if amounts["short_term"] + amounts["long_term"] != amounts["realized"]:
            issues["term_amounts_do_not_add"].append(line)
        flagged = row["Wash Sale?"].strip().lower() == "yes"
        difference = amounts["realized"] - (amounts["proceeds"] - amounts["broker_basis"])
        if difference:
            check = (
                "gain_difference_matches_reported_disallowed_loss"
                if flagged and abs(difference) == abs(amounts["disallowed_loss_reported"])
                else "unexplained_gain_difference"
            )
            issues[check].append(line)
        if flagged != bool(amounts["disallowed_loss_reported"]):
            issues["wash_flag_and_amount_differ"].append(line)
        for key in ("year", underlying):
            for field, amount in amounts.items():
                totals[key][field] += amount
        details.append({
            "broker_source_line": line, "underlying": underlying, "opened": opened.isoformat(),
            "closed": closed.isoformat(), "term": row["Term"], "wash_sale_flag": flagged,
            "opening_predates_transaction_export": opened < first_effective, **amounts,
        })

    monthly = {}
    for month in range(1, 13):
        label = f"{prefix}-{month:02d}"
        rows = [row for row in transactions if row.posted_date.isoformat().startswith(label)]
        groups = realized_comparison(transactions, realized_path, label)
        monthly[label] = {
            "transaction_rows": len(rows), "net_transaction_cash": cash_total(rows),
            "option_close_comparison": groups,
        }
    return {
        "year": year,
        "source_scope": {"first_posted": first_posted.isoformat(), "last_posted": last_posted.isoformat(),
                         "first_effective": first_effective.isoformat()},
        "broker_lots_by_term": Counter(row["term"] for row in details),
        "reported_wash_sale_lots": sum(row["wash_sale_flag"] for row in details),
        "lots_opened_before_export": sum(row["opening_predates_transaction_export"] for row in details),
        "broker_control_checks": issues,
        "reported_amounts": totals,
        "broker_lots": details,
        "monthly": monthly,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transactions", type=Path)
    parser.add_argument("realized", type=Path)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = review(read_export(args.transactions), args.realized, args.year)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
