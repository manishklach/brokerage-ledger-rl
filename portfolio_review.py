"""Build a local portfolio review and answer the 20 documented benchmark queries."""

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from ledger import number, read_export, realized_date, rejected_row, transaction_date
from ledger_evidence import decide, recorded_claim
from period_review import read_schwab_realized, review_lots
from reconcile import contract, export_rows

ZERO = Decimal(0)
AMOUNTS = ("proceeds", "broker_basis", "realized", "short_term", "long_term", "disallowed_loss_reported")
HOLDINGS_FIELDS = {"Symbol", "Qty (Quantity)", "Mkt Val (Market Value)", "Gain $ (Gain/Loss $)", "Asset Type"}


def optional_number(value):
    return None if value.strip().upper() in {"", "-", "--", "N/A"} else number(value)


def read_holdings(path, *, diagnostics=None):
    with path.open(encoding="utf-8-sig") as source:
        header = source.readline()
    found = re.search(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b", header)
    rows = []
    for line, row in export_rows(path, HOLDINGS_FIELDS, diagnostics=diagnostics):
        if row["Asset Type"] == "--":
            continue
        try:
            option = contract(row["Symbol"]) if row["Asset Type"] == "Option" else None
            if row["Asset Type"] == "Option" and option is None:
                raise ValueError("Invalid option instrument")
            qty = optional_number(row["Qty (Quantity)"])
            mark = optional_number(row["Mkt Val (Market Value)"])
            gain = optional_number(row["Gain $ (Gain/Loss $)"])
        except (ArithmeticError, ValueError, AttributeError):
            rejected_row(path, line, "invalid holdings instrument or numeric field", diagnostics)
            continue
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


def realized_position_extremes(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["instrument"]].append(row)
    positions = [{"instrument": instrument, **realized_summary(lots)}
                 for instrument, lots in sorted(groups.items())]
    gains = max((position["realized"] for position in positions), default=ZERO)
    losses = min((position["realized"] for position in positions), default=ZERO)
    return {
        "biggest_realized_gains": [p for p in positions if gains > ZERO and p["realized"] == gains],
        "biggest_realized_losses": [p for p in positions if losses < ZERO and p["realized"] == losses],
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


def answer_questions(monthly, annual, holdings, evidence_index, targets, query_config=None):
    query_config = query_config or {}
    def answer(status, data=None, missing=()):
        return {"status": status, "data": data, "missing": list(missing)}

    positions = holdings["target_positions"]
    marked = holdings["ranked_marks"]
    target_marks = [row for row in marked if row["underlying"] in targets]

    def largest(ticker):
        return max((r for r in positions.get(ticker, {}).get("options", []) if r["market_value"] is not None),
                   key=lambda r: abs(r["market_value"]), default=None)

    first_target = next(iter(targets), None)
    mark_option = largest(query_config.get("mark_ticker", first_target))
    stress_option = largest(query_config.get("stress_ticker", first_target))
    spread_options = positions.get(query_config.get("spread_ticker", first_target), {}).get("options", [])
    short_options = [r for r in holdings["target_rows"]
                     if r["is_option"] and r["quantity"] is not None and r["quantity"] < 0]
    potential = sorted(short_options, key=lambda row: abs(row["quantity"]) * Decimal(row["symbol"].split()[2]),
                       reverse=True)
    expiry = holdings["target_expirations"]
    largest_expiry = max(expiry, key=lambda day: expiry[day]["gross_mark"], default=None)
    evidence_month = query_config.get("evidence_month", monthly["month"])
    evidence_ticker = query_config.get("evidence_ticker", first_target)
    indexed = [r for r in evidence_index if r["month"] == evidence_month
               and (evidence_ticker is None or r["contract"].split()[0] == evidence_ticker)]
    indexed_closes = {"scope": f"{evidence_month} evidence index", "matches": [
        {key: r[key] for key in ("id", "contract", "close_lines")} for r in indexed
    ]}
    if len(indexed) == 1:
        indexed_closes["evidence"] = decide(*recorded_claim(indexed[0]))
        evidence_answer = answer("answered", indexed_closes)
    elif indexed:
        evidence_answer = answer("clarification_needed", indexed_closes, ("intended contract or close ID",))
    else:
        evidence_answer = answer("missing_input", indexed_closes, ("verified close index for the selected month",))
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
        11: answer("partial", mark_option, ("opening fills, fees, and remaining-lot links for the current position",)),
        12: answer("clarification_needed", spread_options, ("intended spread and confirmed legs", "entry cash", "deliverables")),
        13: answer("partial", stress_option, ("spot", "scenario date", "volatility assumptions", "option pricing inputs")),
        14: answer("clarification_needed", spread_options, ("confirmed short leg and spread membership", "deliverables")),
        15: answer("missing_input", missing=("transaction and realized history through the holdings snapshot",
                                             "remaining-lot links for the partial close")),
        16: answer("missing_input", missing=("order confirmations linking closing and opening legs",)),
        17: evidence_answer,
        18: answer("partial", mark_option, ("timestamped option bid and ask",)),
        19: answer("answered", {"period": str(monthly["year"]), "scope": "All realized lots in the supplied broker export",
                                "annual_total": realized_summary(annual),
                                "position_extremes": realized_position_extremes(annual),
                                "by_underlying": tax}),
        20: answer("partial" if wash_flags else "answered",
                   {"period": str(monthly["year"]), "scope": "provided broker export",
                    "flagged_lots": wash_flags,
                    "by_underlying": {root: tax[root]["disallowed_loss_reported"] for root in targets}},
                   ("replacement-lot identifiers and confirmation of full account coverage",) if wash_flags else ()),
    }


def build_portfolio_report(transactions, realized_lots, positions, period, as_of, targets, index=(), *, date_basis="effective", query_config=None):
    """Analyze normalized records without reading broker exports."""
    year = period.year
    month_label = period.strftime("%Y-%m")
    transactions = list(transactions)
    positions = list(positions)
    annual = review_lots(transactions, realized_lots, year, date_basis=date_basis)
    lots = annual["broker_lots"]
    month_lots = [r for r in lots if realized_date(r, date_basis).startswith(month_label + "-")]
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
    answers = answer_questions(month, lots, holdings, index, targets, query_config)
    year_transactions = [row for row in transactions if transaction_date(row, date_basis).year == year]
    posted = [row.posted_date.isoformat() for row in year_transactions]
    closed = [realized_date(row, date_basis) for row in lots]
    return {
        "report_year": year,
        "date_basis": date_basis,
        "coverage": {
            "transaction_posted_from": min(posted, default=None),
            "transaction_posted_through": max(posted, default=None),
            "realized_closes_from": min(closed, default=None),
            "realized_closes_through": max(closed, default=None),
        },
        "transactions": [asdict(row) for row in year_transactions],
        "realized_lots": lots,
        "holdings_snapshot": {"as_of": as_of.isoformat(), "positions": positions},
        "monthly": month, "holdings": holdings, "answers": answers,
        "answer_status_counts": Counter(a["status"] for a in answers.values()),
    }


def read_portfolio_config(path):
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict) or set(config) - {"schema_version", "tickers", "queries", "month", "as_of"}:
        raise ValueError("Invalid portfolio config fields")
    if config.get("schema_version", 1) != 1:
        raise ValueError("Unsupported portfolio config schema")
    tickers = config.get("tickers", [])
    ticker_pattern = r"[A-Z0-9][A-Z0-9./-]*"
    if not isinstance(tickers, list) or not all(isinstance(t, str) and re.fullmatch(ticker_pattern, t)
                                                for t in tickers):
        raise ValueError("Config tickers must be a list of symbols")
    queries = config.get("queries", {})
    ticker_fields = {"mark_ticker", "spread_ticker", "stress_ticker", "evidence_ticker"}
    if not isinstance(queries, dict) or set(queries) - ticker_fields - {"evidence_month"}:
        raise ValueError("Invalid saved query fields")
    if not all(isinstance(queries[name], str) and re.fullmatch(ticker_pattern, queries[name])
               for name in queries.keys() & ticker_fields):
        raise ValueError("Invalid saved query ticker")
    for name, value in (("month", config.get("month")), ("evidence_month", queries.get("evidence_month"))):
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
                raise ValueError(f"{name} must use YYYY-MM")
            date.fromisoformat(value + "-01")
    if "as_of" in config:
        if not isinstance(config["as_of"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", config["as_of"]):
            raise ValueError("as_of must use YYYY-MM-DD")
        date.fromisoformat(config["as_of"])
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transactions", type=Path)
    parser.add_argument("realized", type=Path)
    parser.add_argument("holdings", type=Path)
    parser.add_argument("--month")
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--tickers", nargs="+")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--date-basis", choices=("effective", "posted"), default="effective")
    parser.add_argument("--evidence-index", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    diagnostics = []
    try:
        config = read_portfolio_config(args.config) if args.config else {}
        month = args.month or config.get("month")
        if not month:
            parser.error("Provide --month or a config month")
        period = date.fromisoformat(month + "-01")
        export_date, positions = read_holdings(args.holdings, diagnostics=diagnostics)
        as_of = args.as_of or (date.fromisoformat(config["as_of"]) if "as_of" in config else export_date)
        if as_of is None:
            parser.error("Provide --as-of or a dated holdings export")
        if export_date is not None and export_date != as_of:
            parser.error("--as-of or the configured date disagrees with the holdings export")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    index = json.loads(args.evidence_index.read_text(encoding="utf-8")) if args.evidence_index else []
    if args.tickers is not None:
        targets = args.tickers
    else:
        targets = config.get("tickers", sorted({row["underlying"] for row in positions}))
    report = {
        "sources": {"transactions": args.transactions.name, "realized": args.realized.name,
                    "holdings": args.holdings.name},
        **build_portfolio_report(
            read_export(args.transactions, diagnostics=diagnostics),
            read_schwab_realized(args.realized, diagnostics=diagnostics), positions,
            period, as_of, targets, index, date_basis=args.date_basis, query_config=config.get("queries"),
        ),
    }
    report.update(warning_count=len(diagnostics), warnings=diagnostics)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
