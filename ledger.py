"""Read a Schwab export and report exact cash activity and spread hypotheses."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable
from warnings import warn

HEADERS = ("Date", "Action", "Symbol", "Description", "Quantity", "Price", "Fees & Comm", "Amount")
OPTION_ACTIONS = {
    "Buy to Open": ("open", "buy"),
    "Sell to Open": ("open", "sell"),
    "Buy to Close": ("close", "buy"),
    "Sell to Close": ("close", "sell"),
}


def validate_date_basis(date_basis):
    if date_basis not in {"posted", "effective"}:
        raise ValueError("date_basis must be posted or effective")


def transaction_date(row, date_basis):
    return row.effective_date if date_basis == "effective" else row.posted_date


def realized_date(lot, date_basis):
    if date_basis == "effective":
        return lot.get("transaction_closed") or lot["closed"]
    return lot["closed"]


def parse_date(value: str) -> date:
    value = value.strip()
    if "-" in value:
        return date.fromisoformat(value)
    return datetime.strptime(value, "%m/%d/%Y").date()


def number(value: str) -> Decimal | None:
    value = value.strip().replace("$", "").replace(",", "")
    if not value:
        return None
    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1].strip()
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Expected a finite number")
    return result


@dataclass(frozen=True)
class Transaction:
    source_line: int
    posted_date: date
    effective_date: date
    action: str
    symbol: str
    description: str
    quantity: Decimal | None
    price: Decimal | None
    fees: Decimal | None
    amount: Decimal | None


def rejected_row(path, line, reason, diagnostics):
    if diagnostics is None:
        warn(f"{path.name}:{line}: {reason}", stacklevel=3)
    else:
        diagnostics.append({"file": path.name, "line": line, "reason": reason})


def read_export(path: Path, *, diagnostics: list[dict] | None = None) -> list[Transaction]:
    transactions = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source, strict=True)
        for row in reader:
            header = [cell.strip() for cell in row]
            if len(header) == len(set(header)) and set(HEADERS) <= set(header):
                columns = [header.index(name) for name in HEADERS]
                break
        else:
            raise ValueError("Missing or duplicate Schwab transaction header columns")
        while True:
            line = reader.line_num + 1
            try:
                row = next(reader, None)
            except csv.Error:
                rejected_row(path, line, "invalid CSV record", diagnostics)
                continue
            if row is None:
                break
            if not row or not any(cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                rejected_row(path, line, f"expected {len(header)} columns", diagnostics)
                continue
            row = [row[column] for column in columns]
            posted, _, effective = row[0].strip().partition(" as of ")
            try:
                transactions.append(Transaction(
                    line, parse_date(posted), parse_date(effective or posted),
                    *(value.strip() for value in row[1:4]),
                    *(number(value) for value in row[4:]),
                ))
            except (ArithmeticError, ValueError):
                rejected_row(path, line, "invalid date or numeric field", diagnostics)
    return transactions


def cash_total(transactions: Iterable[Transaction]) -> Decimal:
    return sum((row.amount for row in transactions if row.amount is not None), Decimal("0.00"))


def spread_candidates(transactions: list[Transaction], *, date_basis="effective") -> tuple[list[dict], list[int]]:
    """Return mutually unique vertical candidates and ambiguous source lines."""
    validate_date_basis(date_basis)
    buckets = defaultdict(lambda: {"buy": [], "sell": []})
    for row in transactions:
        if row.action not in OPTION_ACTIONS or not row.quantity:
            continue
        parts = row.symbol.split()
        if len(parts) != 4 or parts[3] not in {"P", "C"}:
            continue
        root, expiry, strike, option_type = parts
        phase, side = OPTION_ACTIONS[row.action]
        buckets[(transaction_date(row, date_basis), phase, root, expiry, option_type, abs(row.quantity))][side].append(
            (row, number(strike))
        )

    candidates = []
    ambiguous = set()
    for key, sides in buckets.items():
        edges = [
            (buy, sell)
            for buy, buy_strike in sides["buy"]
            for sell, sell_strike in sides["sell"]
            if buy_strike != sell_strike
        ]
        degree = Counter(row.source_line for pair in edges for row in pair)
        for buy, sell in edges:
            lines = [buy.source_line, sell.source_line]
            if any(degree[line] != 1 for line in lines):
                ambiguous.update(lines)
                continue
            candidates.append({
                date_basis + "_date": key[0].isoformat(),
                "phase": key[1],
                "source_lines": sorted(lines),
                "net_cash": (
                    str(cash_total((buy, sell)))
                    if all(row.amount is not None for row in (buy, sell))
                    else None
                ),
            })
    return sorted(candidates, key=lambda item: item["source_lines"]), sorted(ambiguous)


def audit(transactions: list[Transaction], *, date_basis="effective") -> dict:
    validate_date_basis(date_basis)
    groups = defaultdict(list)
    for row in transactions:
        groups[row.action].append(row)
    spreads, ambiguous = spread_candidates(transactions, date_basis=date_basis)
    return {
        "date_basis": date_basis,
        "transaction_count": len(transactions),
        "first_posted_date": min((row.posted_date.isoformat() for row in transactions), default=None),
        "last_posted_date": max((row.posted_date.isoformat() for row in transactions), default=None),
        "adjusted_date_count": sum(row.posted_date != row.effective_date for row in transactions),
        "net_transaction_cash": str(cash_total(transactions)),
        "missing_amount_source_lines": [row.source_line for row in transactions if row.amount is None],
        "by_action": {
            action: {"count": len(rows), "net_cash": str(cash_total(rows))}
            for action, rows in sorted(groups.items())
        },
        "vertical_spread_candidates": spreads,
        "ambiguous_spread_source_lines": ambiguous,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--output", type=Path, help="Write the private audit JSON to this path")
    parser.add_argument("--date-basis", choices=("effective", "posted"), default="effective")
    args = parser.parse_args()
    diagnostics = []
    report_data = audit(read_export(args.csv, diagnostics=diagnostics), date_basis=args.date_basis)
    report_data.update(warning_count=len(diagnostics), warnings=diagnostics)
    report = json.dumps(report_data, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
