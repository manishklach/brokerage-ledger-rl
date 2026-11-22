"""Build a local portfolio review and answer the 20 documented benchmark queries."""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ledger import number, read_export
from ledger_evidence import decide, recorded_claim
from period_review import read_schwab_realized, review_lots
from reconcile import contract, export_rows

ZERO = Decimal(0)
AMOUNTS = ("proceeds", "broker_basis", "realized", "short_term", "long_term", "disallowed_loss_reported")
HOLDINGS_FIELDS = {"Symbol", "Qty (Quantity)", "Mkt Val (Market Value)", "Gain $ (Gain/Loss $)", "Asset Type"}


def optional_number(value):
    return None if value.strip().upper() in {"", "-", "--", "N/A"} else number(value)


def read_holdings(path):
    with path.open(encoding="utf-8-sig") as source:
        header = source.readline()
    found = re.search(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b", header)
    rows = []
    for line, row in export_rows(path, HOLDINGS_FIELDS):
        if row["Asset Type"] == "--":
            continue
        option = contract(row["Symbol"]) if row["Asset Type"] == "Option" else None
        if row["Asset Type"] == "Option" and option is None:
            raise ValueError(f"Invalid option instrument at holdings row {line}")
        try:
            qty = optional_number(row["Qty (Quantity)"])
            mark = optional_number(row["Mkt Val (Market Value)"])
            gain = optional_number(row["Gain $ (Gain/Loss $)"])
        except InvalidOperation as error:
            raise ValueError(f"Invalid numeric field at holdings row {line}") from error
        rows.append({"source_line": line, "symbol": option or row["Symbol"],
                     "underlying": option.split()[0] if option else row["Symbol"],
                     "kind": row["Asset Type"], "quantity": qty,
                     "market_value": mark, "unrealized": gain, "is_option": option is not None})
    return (date.fromisoformat(found[0].replace("/", "-")) if found else None), rows


def total(rows, field, *, absolute=False):
    return sum((abs(r[field]) if absolute else r[field] for r in rows if r[field] is not None), ZERO)


def source_lines(rows):
    return sorted(r["source_line"] for r in rows)


def by_underlying(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["underlying"]].append(row)
    return groups


def realized_summary(rows):
    return {
        "lot_count": len(rows),
        "broker_source_lines": sorted(row["broker_source_line"] for row in rows),
        **{field: total(rows, field) for field in AMOUNTS},
    }


def holdings_review(rows, as_of, targets):
    securities = [r for r in rows if r["kind"] in {"Equity", "ETFs & Closed End Funds", "Option"}]
    options = [r for r in rows if r["is_option"]]
    groups = by_underlying(securities)
    ranked = []
    for root, positions in groups.items():
        net = total(positions, "market_value")
        ranked.append({
            "underlying": root, "net_mark": net, "gross_mark": total(positions, "market_value", absolute=True),
            "share_mark": total([r for r in positions if not r["is_option"]], "market_value"),
            "option_mark": total([r for r in positions if r["is_option"]], "market_value"),
            "long_mark": sum((r["market_value"] for r in positions if r["market_value"] is not None and r["market_value"] > 0), ZERO),
            "short_mark": sum((r["market_value"] for r in positions if r["market_value"] is not None and r["market_value"] < 0), ZERO),
            "source_lines": source_lines(positions),
            "unavailable_mark_rows": source_lines([r for r in positions if r["market_value"] is None]),
        })
    ranked.sort(key=lambda position: (-abs(position["net_mark"]), position["underlying"]))
    for index, position in enumerate(ranked, 1):
        position["rank"] = index
    target_rows = [r for r in securities if r["underlying"] in targets]
    target_options = [r for r in target_rows if r["is_option"]]
    gross = total(securities, "market_value", absolute=True)
    target_gross = total(target_rows, "market_value", absolute=True)
    expiry = defaultdict(list)
    for row in options:
        expiry[date.fromisoformat(row["symbol"].split()[1])].append(row)

    def summarize(options):
        return {
            "long_contracts": sum((r["quantity"] for r in options if r["quantity"] is not None and r["quantity"] > 0), ZERO),
            "short_contracts": sum((-r["quantity"] for r in options if r["quantity"] is not None and r["quantity"] < 0), ZERO),
            "gross_mark": total(options, "market_value", absolute=True),
            "source_lines": source_lines(options),
        }

    windows = {
        n: summarize([row for day, positions in expiry.items() if 0 <= (day - as_of).days <= n for row in positions])
        for n in (7, 30, 90)
    }
    target_expiries = {day.isoformat(): summarize([r for r in positions if r["underlying"] in targets])
                       for day, positions in expiry.items()
                       if day >= as_of and any(r["underlying"] in targets for r in positions)}
    ranked_gains = sorted(
        ({"underlying": root, "reported_unrealized": total(group, "unrealized"),
          "source_lines": source_lines(group), "missing_rows": source_lines([r for r in group if r["unrealized"] is None])}
         for root, group in by_underlying(rows).items()),
        key=lambda item: (-abs(item["reported_unrealized"]), item["underlying"]),
    )
    return {
        "as_of": as_of.isoformat(), "ranked_marks": ranked, "target_rows": target_rows,
        "target_positions": {root: {
            "share_rows": [r for r in target_rows if r["underlying"] == root and not r["is_option"]],
            "options": [r for r in target_options if r["underlying"] == root],
        } for root in targets},
        "concentration": {
            "scope": "Gross absolute marks for shares and options, excluding cash",
            "target_gross_mark": target_gross, "gross_share_option_mark": gross,
            "target_share_percent": (target_gross * 100 / gross).quantize(Decimal("0.01")) if gross else None,
            "missing_marks": source_lines([r for r in securities if r["market_value"] is None]),
        },
        "cumulative_expiration_windows": windows, "target_expirations": target_expiries,
        "unrealized_by_underlying": ranked_gains, "unrealized_reported_total": total(rows, "unrealized"),
        "unrealized_missing_rows": source_lines([r for r in rows if r["unrealized"] is None]),
        "cash_mark_rows": [r for r in rows if r["kind"] == "Cash and Money Market"],
    }


def answer_questions(monthly, annual, holdings, evidence_index, targets):
    def answer(status, data=None, missing=()):
        return {"status": status, "data": data, "missing": list(missing)}

    positions = holdings["target_positions"]
    marked = holdings["ranked_marks"]
    target_marks = [row for row in marked if row["underlying"] in targets]

    def largest(ticker):
        return max((r for r in positions.get(ticker, {}).get("options", []) if r["market_value"] is not None),
                   key=lambda r: abs(r["market_value"]), default=None)

    tqqq, xlk = largest("TQQQ"), largest("XLK")
    soxl = positions.get("SOXL", {}).get("options", [])
    short_options = [r for r in holdings["target_rows"]
                     if r["is_option"] and r["quantity"] is not None and r["quantity"] < 0]
    potential = sorted(short_options, key=lambda row: abs(row["quantity"]) * Decimal(row["symbol"].split()[2]),
                       reverse=True)
    expiry = holdings["target_expirations"]
    largest_expiry = max(expiry, key=lambda day: expiry[day]["gross_mark"], default=None)
    september_xlk = [r for r in evidence_index if r["month"] == "2026-09" and r["contract"].startswith("XLK ")]
    indexed_closes = {"scope": "September 2026 evidence index", "matches": [
        {key: r[key] for key in ("id", "contract", "close_lines")} for r in september_xlk
    ]}
    if len(september_xlk) == 1:
        indexed_closes["evidence"] = decide(*recorded_claim(september_xlk[0]))
        september_answer = answer("answered", indexed_closes)
    elif september_xlk:
        september_answer = answer("clarification_needed", indexed_closes, ("intended contract or close ID",))
    else:
        september_answer = answer("missing_input", indexed_closes, ("verified full September close index",))
    tax = {root: realized_summary([r for r in annual if r["underlying"] == root]) for root in targets}
    wash_flags = [r for r in annual if r["underlying"] in targets and r["wash_sale_flag"]]
    return {
        1: answer("answered", {"scope": "shares and options with marks; rank by absolute net mark",
                               "top": marked[:5], "targets": target_marks}),
        2: answer("partial", holdings["concentration"], ("underlying spot prices", "option delta", "contract multipliers")),
        3: answer("answered", {"measurement": "signed marked value; gross is absolute row marks",
                               "exposure_by_underlying": target_marks}),
        4: answer("answered", {"realized_month": monthly, "holdings_as_of": holdings["as_of"],
                               "unrealized_reported_total": holdings["unrealized_reported_total"],
                               "unrealized_missing_rows": holdings["unrealized_missing_rows"],
                               "unrealized_by_underlying": holdings["unrealized_by_underlying"]}),
        5: answer("answered", {"cumulative": True, "as_of": holdings["as_of"],
                               "windows": holdings["cumulative_expiration_windows"],
                               "top_target_expiry_by_gross_mark": largest_expiry,
                               "top_target_expiry_totals": expiry.get(largest_expiry)}),
        6: answer("missing_input", missing=("timestamped spots", "volatility or adequate scenario Greeks", "verified deliverables", "repricing inputs")),
        7: answer("partial", {"screen_only": "rank by absolute contracts times strike; obligations unverified",
                              "candidates": potential[:5]}, ("confirmed contract deliverables",)),
        8: answer("partial", target_marks, ("dated ETF constituent holdings or comparable return histories",)),
        9: answer("partial", {"cash_and_money_market_marks": holdings["cash_mark_rows"],
                              "total_mark": total(holdings["cash_mark_rows"], "market_value")},
                  ("available settled cash", "reported buying power", "deliverables", "broker margin inputs")),
        10: answer("answered", {"as_of": holdings["as_of"], "positions": positions}),
        11: answer("partial", tqqq, ("opening fills, fees, and remaining-lot links for the current position",)),
        12: answer("clarification_needed", soxl, ("intended spread and confirmed legs", "entry cash", "deliverables")),
        13: answer("partial", xlk, ("spot", "scenario date", "volatility assumptions", "option pricing inputs")),
        14: answer("clarification_needed", soxl, ("confirmed short leg and spread membership", "deliverables")),
        15: answer("missing_input", missing=("transaction and realized history through the holdings snapshot",
                                             "remaining-lot links for the partial close")),
        16: answer("missing_input", missing=("order confirmations linking closing and opening TQQQ legs",)),
        17: september_answer,
        18: answer("partial", tqqq, ("timestamped option bid and ask",)),
        19: answer("answered", {"period": str(monthly["year"]), "scope": "All realized lots in the supplied broker export",
                                "annual_total": realized_summary(annual),
                                "by_underlying": tax}),
        20: answer("partial" if wash_flags else "answered",
                   {"period": str(monthly["year"]), "scope": "provided broker export",
                    "flagged_lots": wash_flags,
                    "by_underlying": {root: tax[root]["disallowed_loss_reported"] for root in targets}},
                   ("replacement-lot identifiers and confirmation of full account coverage",) if wash_flags else ()),
    }


def build_portfolio_report(transactions, realized_lots, positions, period, as_of, targets, index=()):
    """Analyze normalized records without reading broker exports."""
    year = period.year
    month_label = period.strftime("%Y-%m")
    annual = review_lots(transactions, realized_lots, year)
    lots = annual["broker_lots"]
    month_lots = [r for r in lots if r["closed"].startswith(month_label + "-")]
    month = {
        "month": month_label, "year": year, "realized": realized_summary(month_lots),
        "by_underlying": dict(sorted(
            ((root, realized_summary(group)) for root, group in by_underlying(month_lots).items()),
            key=lambda item: (-abs(item[1]["realized"]), item[0]),
        )),
        "monthly_transaction_review": annual["monthly"][month_label],
        "broker_lots": month_lots,
    }
    holdings = holdings_review(positions, as_of, targets)
    answers = answer_questions(month, lots, holdings, index, targets)
    return {
        "monthly": month, "holdings": holdings, "answers": answers,
        "answer_status_counts": Counter(a["status"] for a in answers.values()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transactions", type=Path)
    parser.add_argument("realized", type=Path)
    parser.add_argument("holdings", type=Path)
    parser.add_argument("--month", required=True)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    parser.add_argument("--tickers", nargs="+", default=["TQQQ", "SOXL", "XLK"])
    parser.add_argument("--evidence-index", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        period = date.fromisoformat(args.month + "-01")
    except ValueError:
        parser.error("--month must use YYYY-MM")
    as_of, positions = read_holdings(args.holdings)
    if as_of is not None and as_of != args.as_of:
        parser.error("--as-of disagrees with the holdings export date")
    index = json.loads(args.evidence_index.read_text(encoding="utf-8")) if args.evidence_index else []
    report = {
        "sources": {"transactions": args.transactions.name, "realized": args.realized.name,
                    "holdings": args.holdings.name},
        **build_portfolio_report(
            read_export(args.transactions), read_schwab_realized(args.realized), positions,
            period, args.as_of, args.tickers, index,
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
