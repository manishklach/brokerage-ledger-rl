"""Produce an auditable, read-only reconciliation report."""

import argparse
import hashlib
import json
import os
import tempfile
from importlib.metadata import version
from pathlib import Path

from ledger import audit, read_export
from option_lots import match_options
from period_review import read_schwab_realized, review_lots


def input_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_report(path, content):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transactions", type=Path)
    parser.add_argument("--realized", type=Path)
    parser.add_argument("--year", type=int, choices=range(1, 10000), metavar="YYYY")
    parser.add_argument("--date-basis", choices=("effective", "posted"), default="effective")
    parser.add_argument("--format", choices=("json",), default="json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if (args.realized is None) != (args.year is None):
        parser.error("--realized and --year must be supplied together")

    try:
        inputs = [path.resolve(strict=True) for path in (args.transactions, args.realized) if path is not None]
        output = args.output.resolve()
        if args.output.suffix.lower() != ".json":
            parser.error("--output must end in .json")
        if any(part.casefold() == "private" for path in (args.output.absolute(), output) for part in path.parent.parts):
            parser.error("--output cannot write inside a private directory")
        if output in inputs or (output.exists() and any(output.samefile(path) for path in inputs)):
            parser.error("--output must be separate from the source exports")
        inputs_meta = [{"file": p.name, "sha256": input_digest(p)} for p in inputs]
        warnings = []
        transactions = read_export(inputs[0], diagnostics=warnings)
        inputs_meta[0].update(accepted_rows=len(transactions), rejected_rows=len(warnings))
        options = match_options(transactions, None, date_basis=args.date_basis)
        report = {
            "audit": {"version": version("brokerage-ledger-rl"), "schema_version": 1,
                      "date_basis": args.date_basis, "year": args.year, "inputs": inputs_meta},
            "warnings": warnings,
            "transactions": audit(transactions, date_basis=args.date_basis),
            "options": options,
        }
        if args.realized is not None:
            before = len(warnings)
            lots = list(read_schwab_realized(inputs[1], diagnostics=warnings))
            inputs_meta[1].update(accepted_rows=len(lots), rejected_rows=len(warnings) - before)
            report["period"] = review_lots(transactions, lots, args.year, date_basis=args.date_basis)
        if any(item["sha256"] != input_digest(path) for path, item in zip(inputs, inputs_meta, strict=True)):
            raise ValueError("Source export changed during the review")
        report["warning_count"] = len(warnings)
        report["blocker_count"] = (
            len(warnings)
            + sum(map(len, options["unresolved_contracts"].values()))
            + sum(close["status"] == "insufficient_open_quantity" for close in options["closes"])
        )
        write_report(output, json.dumps(report, indent=2, default=str) + "\n")
    except (OSError, ValueError, ArithmeticError) as error:
        parser.error(str(error))
    return int(bool(report["blocker_count"]))


if __name__ == "__main__":
    raise SystemExit(main())
