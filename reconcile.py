"""Compare option closes and open option quantities with Schwab exports."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from ledger import number, parse_date, read_export
from option_lots import match_options


def contract(symbol):
    parts = symbol.split()
    if len(parts) != 4 or parts[3] not in {"C", "P"}:
        return None
    root, expiry, strike, right = parts
    expiry_date = date.fromisoformat(expiry) if "-" in expiry else parse_date(expiry)
    return f"{root} {expiry_date} {number(strike).normalize():f} {right}"


def export_rows(path, required):
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source, strict=True)
        for row in reader:
            if required <= set(row):
                header = row
                break
        else:
            raise ValueError(f"Missing required export columns: {sorted(required)}")
        while True:
            line = reader.line_num + 1
            row = next(reader, None)
            if row is None:
                return
            if not any(row) or not row[0].strip():
                continue
            if len(row) != len(header):
                raise ValueError(f"Unexpected column count at source line {line}")
            yield line, dict(zip(header, row, strict=True))


def realized_comparison(transactions, path, month):
    required = {"Symbol", "Closed Date", "Opened Date", "Quantity", "Gain/Loss ($)", "Wash Sale?"}
    lots = (
        {"instrument": contract(row["Symbol"]), "closed": parse_date(row["Closed Date"]).isoformat(),
         "broker_source_line": line, "opened": parse_date(row["Opened Date"]).isoformat(),
         "transaction_closed": parse_date(row.get("Transaction Closed Date") or row["Closed Date"]).isoformat(),
         "quantity": abs(number(row["Quantity"])), "realized": number(row["Gain/Loss ($)"]),
         "wash_sale_flag": row["Wash Sale?"].strip().lower() == "yes"}
        for line, row in export_rows(path, required)
        if contract(row["Symbol"])
    )
    return compare_realized_lots(transactions, lots, month)


def compare_realized_lots(transactions, lots, month):
    modeled = match_options(transactions, None)["closes"]
    return compare_close_groups(modeled, lots, month)


def compare_close_groups(closes, lots, month):
    modeled = defaultdict(list)
    broker = defaultdict(list)
    for lot in lots:
        closed = lot.get("transaction_closed") or lot["closed"]
        if lot["instrument"] and lot.get("is_option", True) and closed.startswith(month + "-"):
            broker[lot["instrument"], closed].append({
                "line": lot["broker_source_line"], "opened": lot["opened"],
                "quantity": lot["quantity"], "pnl": lot["realized"],
                "wash_sale": lot["wash_sale_flag"],
            })
    for row in closes:
        if row["effective_date"].startswith(month + "-"):
            modeled[contract(row["contract"]), row["effective_date"]].append(row)

    items = []
    for (symbol, closed), ledger_rows in sorted(modeled.items()):
        broker_rows = broker.pop((symbol, closed), [])
        shares_by_date = defaultdict(Decimal)
        broker_by_date = defaultdict(Decimal)
        for row in ledger_rows:
            for part in row["matches"]:
                shares_by_date[part["open_effective_date"]] += Decimal(part["quantity"])
        for row in broker_rows:
            broker_by_date[row["opened"]] += row["quantity"]
        complete = all(row["provisional_pnl"] is not None for row in ledger_rows)
        trader_pnl = sum(Decimal(row["provisional_pnl"]) for row in ledger_rows) if complete else None
        broker_pnl = sum(row["pnl"] for row in broker_rows) if broker_rows else None
        same_quantity = sum(shares_by_date.values()) == sum(broker_by_date.values())
        if not broker_rows:
            status = "no_same_date_broker_group"
        elif not complete:
            status = "unresolved_ledger"
        elif not same_quantity:
            status = "quantity_difference"
        elif shares_by_date != broker_by_date:
            status = "opening_date_quantity_difference"
        elif trader_pnl != broker_pnl:
            status = "pnl_difference"
        else:
            status = "group_ties"
        items.append({
            "contract": symbol, "closed": closed, "status": status,
            "transaction_lines": [r["close_line"] for r in ledger_rows],
            "broker_lines": [r["line"] for r in broker_rows],
            "ledger_quantity_by_open_date": shares_by_date,
            "broker_quantity_by_open_date": broker_by_date,
            "ledger_pnl": trader_pnl, "broker_pnl": broker_pnl,
            "broker_wash_sale_flag": any(r["wash_sale"] for r in broker_rows),
        })
    return {
        "by_status": Counter(row["status"] for row in items),
        "broker_option_lot_rows": sum(len(row["broker_lines"]) for row in items) + sum(map(len, broker.values())),
        "groups": items,
        "other_broker_groups": [
            {"contract": symbol, "closed": closed, "broker_lines": [r["line"] for r in rows]}
            for (symbol, closed), rows in sorted(broker.items())
        ],
    }


def holdings_comparison(transactions, path, as_of):
    ledger_positions = defaultdict(Decimal)
    snapshot = defaultdict(Decimal)
    issues = defaultdict(list)
    buy = {"Buy to Open", "Buy to Close", "Cancel Sell to Open"}
    sell = {"Sell to Open", "Sell to Close", "Cancel Buy to Open"}
    signed = {"Expired", "Assigned", "Exchange or Exercise", "Options Frwd Split", "Journal"}
    for row in transactions:
        if row.posted_date > as_of:
            continue
        symbol = contract(row.symbol)
        if symbol is None:
            continue
        if row.quantity is None:
            issues[symbol].append({"transaction_line": row.source_line, "reason": "missing_quantity"})
        elif row.action in buy:
            ledger_positions[symbol] += abs(row.quantity)
        elif row.action in sell:
            ledger_positions[symbol] -= abs(row.quantity)
        elif row.action in signed:
            ledger_positions[symbol] += row.quantity
        else:
            issues[symbol].append({"transaction_line": row.source_line, "reason": "unsupported_action",
                                   "action": row.action})
    for line, row in export_rows(path, {"Symbol", "Qty (Quantity)"}):
        symbol = contract(row["Symbol"])
        if symbol:
            try:
                quantity = number(row["Qty (Quantity)"])
            except (ValueError, ArithmeticError):
                issues[symbol].append({"snapshot_line": line, "reason": "invalid_quantity"})
                continue
            if quantity is None:
                issues[symbol].append({"snapshot_line": line, "reason": "missing_quantity"})
            else:
                snapshot[symbol] += quantity
    symbols = {symbol for positions in (ledger_positions, snapshot) for symbol, qty in positions.items() if qty}
    symbols.difference_update(issues)
    differences = [
        {"contract": symbol, "ledger_quantity": ledger_positions[symbol], "snapshot_quantity": snapshot[symbol]}
        for symbol in sorted(symbols) if ledger_positions[symbol] != snapshot[symbol]
    ]
    return {
        "as_of": as_of.isoformat(),
        "snapshot_open_option_contracts": sum(bool(qty) for qty in snapshot.values()),
        "contracts_compared": len(symbols),
        "quantity_ties": len(symbols) - len(differences),
        "differences": differences,
        "unresolved_contracts": dict(sorted(issues.items())),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transactions", type=Path)
    parser.add_argument("realized", type=Path)
    parser.add_argument("holdings", type=Path)
    parser.add_argument("--month", required=True)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = read_export(args.transactions)
    report = {
        "realized": realized_comparison(rows, args.realized, args.month),
        "holdings": holdings_comparison(rows, args.holdings, args.as_of),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
