"""Build and score local held-out cases from a Schwab lot reconciliation."""

import argparse
import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ledger import read_export
from option_lots import match_options
from reconcile import contract


def prediction(matches):
    quantities = defaultdict(Decimal)
    for match in matches:
        for lot in match["matches"]:
            quantities[lot["open_effective_date"]] += Decimal(lot["quantity"])
    values = [match["provisional_pnl"] for match in matches]
    return {
        "quantity_by_open_date": dict(quantities),
        "pnl": sum(map(Decimal, values)) if values and all(v is not None for v in values) else None,
    }


def evaluate(expected, actual):
    try:
        quantities = actual["quantity_by_open_date"]
        pnl = Decimal(actual["pnl"]) if actual["pnl"] is not None else None
        dates = isinstance(quantities, dict) and {
            key: Decimal(value) for key, value in quantities.items()
        } == {key: Decimal(value) for key, value in expected["quantity_by_open_date"].items()}
        cash = pnl is not None and pnl.is_finite() and pnl == Decimal(expected["pnl"])
    except (KeyError, TypeError, InvalidOperation, ValueError):
        return {"opening_allocation": False, "pnl": False, "exact": False}
    return {"opening_allocation": dates, "pnl": cash, "exact": dates and cash}


def build(rows, realized, month):
    fifo = {row["close_line"]: row for row in match_options(rows, month)["closes"]}
    lifo = {row["close_line"]: row for row in match_options(rows, month, newest_first=True)["closes"]}
    history = defaultdict(list)
    for row in rows:
        symbol = contract(row.symbol)
        if symbol:
            history[symbol].append(row)
    cases, differences = [], []
    summaries = {"fifo": Counter(), "lifo": Counter()}
    for group in realized["groups"]:
        if not group["broker_lines"]:
            continue
        expected = {
            "quantity_by_open_date": group["broker_quantity_by_open_date"],
            "pnl": group["broker_pnl"],
        }
        lines = group["transaction_lines"]
        predictions = {
            "fifo": prediction([fifo[line] for line in lines]),
            "lifo": prediction([lifo[line] for line in lines]),
        }
        scores = {name: evaluate(expected, answer) for name, answer in predictions.items()}
        for name, score in scores.items():
            summaries[name].update(key for key, value in score.items() if value)
        if group["status"] == "opening_date_quantity_difference":
            opposite = {"Sell to Close": "Buy to Open", "Buy to Close": "Sell to Open"}
            opening_actions = {opposite[fifo[line]["close_action"]] for line in lines}
            opening_rows = [row for row in history[group["contract"]] if row.action in opening_actions]
            effective_dates = {row.effective_date.isoformat() for row in opening_rows}
            posted_dates = {row.posted_date.isoformat() for row in opening_rows}
            expected_dates = set(expected["quantity_by_open_date"])
            differences.append({
                "transaction_lines": lines, "broker_lines": group["broker_lines"],
                "expected": expected, "predictions": predictions, "scores": scores,
                "broker_dates_missing_from_effective_opens": sorted(expected_dates - effective_dates),
                "broker_dates_missing_from_posted_opens": sorted(expected_dates - posted_dates),
                "broker_wash_sale_flag": group["broker_wash_sale_flag"],
            })
        if group["status"] != "group_ties" or len(lines) != 1 or len(group["broker_lines"]) != 1:
            continue
        close = fifo[lines[0]]
        events = [
            {"line": row.source_line, "effective_date": row.effective_date.isoformat(),
             "action": row.action, "quantity": row.quantity, "amount": row.amount}
            for row in sorted(history[group["contract"]], key=lambda r: (r.effective_date, -r.source_line))
            if (row.effective_date.isoformat(), -row.source_line) <= (close["effective_date"], -lines[0])
        ]
        cases.append({
            "id": f"close-{lines[0]}",
            "input": {"contract": group["contract"], "close_line": lines[0], "events": events},
            "expected": expected, "broker_source_line": group["broker_lines"][0],
        })
    return {
        "cases": cases,
        "diagnostic": {
            "broker_groups_compared": sum(bool(g["broker_lines"]) for g in realized["groups"]),
            "scores": summaries,
            "opening_date_differences": differences,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transactions", type=Path)
    parser.add_argument("reconciliation", type=Path)
    parser.add_argument("--month", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--predictions", type=Path, help="JSON mapping case IDs to prediction objects")
    args = parser.parse_args()
    realized = json.loads(args.reconciliation.read_text(encoding="utf-8"))["realized"]
    report = build(read_export(args.transactions), realized, args.month)
    if args.predictions:
        predictions = json.loads(args.predictions.read_text(encoding="utf-8"), parse_float=Decimal)
        report["evaluation"] = {
            case["id"]: evaluate(case["expected"], predictions.get(case["id"], {}))
            for case in report["cases"]
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
