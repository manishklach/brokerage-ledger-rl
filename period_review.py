"""Review a local Schwab transaction year against broker-reported realized lots."""

import argparse
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from ledger import cash_total, number, parse_date, read_export
from reconcile import contract, export_rows, realized_comparison

FIELDS = {
    "Symbol", "Closed Date", "Opened Date", "Quantity", "Proceeds", "Cost Basis (CB)",
    "Gain/Loss ($)", "Long Term Gain/Loss", "Short Term Gain/Loss", "Term",
    "Wash Sale?", "Disallowed Loss",
}

OPEN_ACTIONS = {"Buy", "Sell Short", "Buy to Open", "Sell to Open", "Reinvest Shares"}
CLOSE_ACTIONS = {"Sell", "Buy to Cover", "Buy to Close", "Sell to Close",
                 "Expired", "Assigned", "Exchange or Exercise"}
OPEN_SIDE = {"Sell": {"Buy", "Reinvest Shares"}, "Buy to Cover": {"Sell Short"},
             "Sell to Close": {"Buy to Open"}, "Buy to Close": {"Sell to Open"}}


def link_broker_lots(transactions, lots, first_effective):
    opening = defaultdict(list)
    closing = defaultdict(list)
    for row in transactions:
        if not row.quantity:
            continue
        key = (contract(row.symbol) or row.symbol, row.effective_date.isoformat())
        if row.action in OPEN_ACTIONS:
            opening[key].append(row)
        elif row.action in CLOSE_ACTIONS:
            closing[key].append(row)

    close_groups = defaultdict(list)
    open_groups = defaultdict(list)
    for lot in lots:
        close_groups[lot["instrument"], lot["transaction_closed"]].append(lot)
        open_groups[lot["instrument"], lot["opened"]].append(lot)

    for key, group in close_groups.items():
        rows = closing[key]
        statuses = {row.action for row in rows}
        exact = len(statuses) == 1 and sum(abs(row.quantity) for row in rows) == sum(
            lot["quantity"] for lot in group
        )
        for lot in group:
            lot["close_evidence"] = {
                "status": "quantity_match" if exact else "unresolved" if rows else "missing",
                "transaction_lines": [row.source_line for row in rows],
                "actions": sorted(statuses),
            }

    for key, group in open_groups.items():
        rows = opening[key]
        for lot in group:
            close = lot["close_evidence"]
            sides = OPEN_SIDE.get(close["actions"][0]) if close["status"] == "quantity_match" else None
            candidates = [row for row in rows if sides is None or row.action in sides]
            status = "predates_export" if lot["opened"] < first_effective.isoformat() else "missing"
            if candidates:
                required = sum(item["quantity"] for item in group)
                available = sum(abs(row.quantity) for row in candidates)
                if available < required:
                    status = "quantity_shortfall"
                elif sides is None:
                    status = "direction_unresolved"
                elif available == required:
                    status = "quantity_match"
                elif len(candidates) == 1:
                    status = "single_row_partial"
                else:
                    status = "ambiguous"
            lot["open_evidence"] = {"status": status,
                                    "transaction_lines": [row.source_line for row in candidates]}


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
        transaction_closed = parse_date(row.get("Transaction Closed Date") or row["Closed Date"])
        option = contract(row["Symbol"])
        underlying = option.split()[0] if option else row["Symbol"]
        quantity = number(row["Quantity"])
        if quantity is None or not quantity:
            raise ValueError(f"Missing realized quantity on broker source line {line}")
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
            "broker_source_line": line, "underlying": underlying, "instrument": option or row["Symbol"],
            "is_option": option is not None, "quantity": abs(quantity), "opened": opened.isoformat(),
            "closed": closed.isoformat(), "transaction_closed": transaction_closed.isoformat(),
            "term": row["Term"], "wash_sale_flag": flagged,
            "opening_predates_transaction_export": opened < first_effective, **amounts,
        })

    link_broker_lots(transactions, details, first_effective)
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
