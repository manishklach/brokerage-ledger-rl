"""Reconstruct provisional FIFO option lots from one Schwab account export."""

import argparse
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from ledger import OPTION_ACTIONS, Transaction, read_export

CENT = Decimal("0.01")


@dataclass
class Lot:
    row: Transaction
    used: Decimal = Decimal(0)


def allocate(amount: Decimal, quantity: Decimal, before: Decimal, after: Decimal) -> Decimal:
    """Allocate cumulative amounts to cents so a fully consumed row ties out."""
    def through(units):
        return (amount * units / quantity).quantize(CENT, rounding=ROUND_HALF_UP)

    return through(after) - through(before)


def match_options(rows: list[Transaction], month: str | None, *, newest_first: bool = False) -> dict:
    contracts = defaultdict(list)
    for row in rows:
        if len(row.symbol.split()) == 4 and row.symbol.split()[-1] in {"C", "P"}:
            contracts[" ".join(row.symbol.split())].append(row)

    closes = []
    other_events = []
    for symbol, events in contracts.items():
        lots = {"buy": deque(), "sell": deque()}
        blockers = []
        for row in sorted(events, key=lambda x: (x.effective_date, -x.source_line)):
            in_month = month is None or row.posted_date.isoformat().startswith(month + "-")
            if row.action not in OPTION_ACTIONS:
                blockers.append(row.source_line)
                if in_month:
                    other_events.append({"line": row.source_line, "action": row.action, "contract": symbol})
                continue

            phase, side = OPTION_ACTIONS[row.action]
            if not row.quantity or row.amount is None:
                blockers.append(row.source_line)
            if phase == "open":
                if not blockers:
                    lots[side].append(Lot(row))
                continue

            result = {
                "close_line": row.source_line,
                "contract": symbol,
                "posted_date": row.posted_date.isoformat(),
                "effective_date": row.effective_date.isoformat(),
                "close_action": row.action,
                "matches": [],
                "provisional_pnl": None,
            }
            if blockers:
                result.update(status="unsupported_contract_event", blocking_lines=sorted(set(blockers)))
            else:
                quantity = abs(row.quantity)
                remaining = quantity
                queue = lots["buy" if side == "sell" else "sell"]
                pnl = Decimal("0.00")
                while remaining and queue:
                    lot = queue[-1] if newest_first else queue[0]
                    opening = lot.row
                    opened = abs(opening.quantity)
                    matched = min(remaining, opened - lot.used)
                    open_cash = allocate(opening.amount, opened, lot.used, lot.used + matched)
                    close_cash = allocate(row.amount, quantity, quantity - remaining, quantity - remaining + matched)
                    result["matches"].append({
                        "open_line": opening.source_line,
                        "open_effective_date": opening.effective_date.isoformat(),
                        "quantity": str(matched),
                        "open_cash": str(open_cash),
                        "close_cash": str(close_cash),
                        "pnl": str(open_cash + close_cash),
                        "same_effective_date": opening.effective_date == row.effective_date,
                    })
                    pnl += open_cash + close_cash
                    remaining -= matched
                    lot.used += matched
                    if lot.used == opened:
                        if newest_first:
                            queue.pop()
                        else:
                            queue.popleft()
                result["unmatched_quantity"] = str(remaining)
                result["status"] = "insufficient_open_quantity" if remaining else ("provisional_lifo" if newest_first else "provisional_fifo")
                if not remaining:
                    result["provisional_pnl"] = str(pnl)
            if in_month:
                closes.append(result)

    closes.sort(key=lambda x: x["close_line"])
    return {
        "month": month,
        "assumptions": [
            "One account, export starts with zero known inventory",
            ("LIFO" if newest_first else "FIFO") + " by effective date; reverse CSV row order breaks ties",
            "Earlier closes consume lots, including previously reported months",
            "Cash uses the reported Amount and includes no second fee deduction",
            "Contract events such as splits, cancellations, assignment and exercise require review",
        ],
        "closes": closes,
        "other_option_events": sorted(other_events, key=lambda x: x["line"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--month", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        month = date.fromisoformat(args.month + "-01").isoformat()[:7]
    except ValueError:
        parser.error("--month must be YYYY-MM")
    report = match_options(read_export(args.csv), month)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
