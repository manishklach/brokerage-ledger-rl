"""Reconstruct provisional FIFO option lots from one Schwab account export."""

import argparse
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from ledger import OPTION_ACTIONS, Transaction, read_export, transaction_date, validate_date_basis

CENT = Decimal("0.01")
CANCELLATION_SIDE = {"Cancel Buy to Open": "buy", "Cancel Sell to Open": "sell"}
SETTLEMENT_ACTIONS = {"Expired", "Assigned", "Exchange or Exercise"}


@dataclass
class Lot:
    row: Transaction
    used: Decimal = Decimal(0)
    settlement_lines: list[int] = field(default_factory=list)


def allocate(amount: Decimal, quantity: Decimal, before: Decimal, after: Decimal) -> Decimal:
    """Allocate cumulative amounts to cents so a fully consumed row ties out."""
    def through(units):
        return (amount * units / quantity).quantize(CENT, rounding=ROUND_HALF_UP)

    return through(after) - through(before)


def match_options(rows: list[Transaction], month: str | None, *, newest_first: bool = False,
                  date_basis: str = "effective") -> dict:
    validate_date_basis(date_basis)
    contracts = defaultdict(list)
    for row in rows:
        if len(row.symbol.split()) == 4 and row.symbol.split()[-1] in {"C", "P"}:
            contracts[" ".join(row.symbol.split())].append(row)

    closes = []
    other_events = []
    unresolved = defaultdict(list)
    for symbol, events in contracts.items():
        lots = {"buy": deque(), "sell": deque()}
        blockers = {"buy": [], "sell": []}
        quarantined = []
        for row in sorted(events, key=lambda x: (x.effective_date, -x.source_line)):
            report_date = transaction_date(row, date_basis)
            in_month = month is None or report_date.isoformat()[:7] == month
            if row.action not in OPTION_ACTIONS:
                event = {"line": row.source_line, "action": row.action, "contract": symbol}
                side = CANCELLATION_SIDE.get(row.action)
                if row.action in SETTLEMENT_ACTIONS and row.quantity:
                    side = "buy" if row.quantity < 0 else "sell"
                    queue = lots[side]
                    quantity = abs(row.quantity)
                    known = sum(abs(lot.row.quantity) - lot.used for lot in queue)
                    if blockers[side] or quantity > known:
                        event["reason"] = "prior_inventory_blocker" if blockers[side] else "insufficient_settlement_inventory"
                    else:
                        event.update(allocation_basis="fifo", allocations=[])
                        while quantity:
                            lot = queue[0]
                            opened = abs(lot.row.quantity)
                            matched = min(quantity, opened - lot.used)
                            open_cash = allocate(lot.row.amount, opened, lot.used, lot.used + matched)
                            event["allocations"].append({"open_line": lot.row.source_line,
                                                         "quantity": str(matched), "open_cash": str(open_cash)})
                            lot.used += matched
                            quantity -= matched
                            lot.settlement_lines.append(row.source_line)
                            if lot.used == opened:
                                queue.popleft()
                else:
                    event["reason"] = ("unresolved_cancellation" if side else
                                       "missing_settlement_quantity" if row.action in SETTLEMENT_ACTIONS else
                                       "unsupported_option_event")
                if "reason" in event:
                    unresolved[symbol].append({**event, "side": side})
                    if side:
                        blockers[side].append(row.source_line)
                    else:
                        quarantined.append(row.source_line)
                if in_month:
                    other_events.append(event)
                continue

            phase, side = OPTION_ACTIONS[row.action]
            inventory_side = side if phase == "open" else ("buy" if side == "sell" else "sell")
            inventory_blockers = blockers[inventory_side]
            if not row.quantity or row.amount is None:
                inventory_blockers.append(row.source_line)
                unresolved[symbol].append({"line": row.source_line, "action": row.action,
                                           "side": inventory_side, "reason": "invalid_trade_quantity_or_cash"})
            if phase == "open":
                if not inventory_blockers:
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
            if quarantined:
                result["quarantined_event_lines"] = list(quarantined)
            if inventory_blockers:
                result.update(status="unsupported_contract_event", blocking_lines=sorted(set(inventory_blockers)))
            else:
                quantity = abs(row.quantity)
                remaining = quantity
                queue = lots[inventory_side]
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
                    if lot.settlement_lines:
                        result["matches"][-1]["prior_settlement_lines"] = list(lot.settlement_lines)
                        result["matches"][-1]["prior_settlement_basis"] = "fifo"
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
        "date_basis": date_basis,
        "assumptions": [
            "One account, export starts with zero known inventory",
            ("LIFO" if newest_first else "FIFO") + " by effective date; reverse CSV row order breaks ties",
            "Earlier closes consume lots, including previously reported months",
            "Cash uses the reported Amount and includes no second fee deduction",
            "Settlements consume known inventory in FIFO order",
            "Quarantined events may affect the reliability of later provisional results",
        ],
        "closes": closes,
        "unresolved_contracts": dict(sorted(unresolved.items())),
        "other_option_events": sorted(other_events, key=lambda x: x["line"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--month", required=True)
    parser.add_argument("--date-basis", choices=("effective", "posted"), default="effective")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        month = date.fromisoformat(args.month + "-01").isoformat()[:7]
    except ValueError:
        parser.error("--month must be YYYY-MM")
    report = match_options(read_export(args.csv), month, date_basis=args.date_basis)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
