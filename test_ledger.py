import tempfile
import unittest
from pathlib import Path
from datetime import date
from decimal import Decimal

from ledger import audit, read_export
from rewards import score_spread

CSV = """Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount
10/03/2026 as of 10/02/2026,Sell to Open,DEMO 11/20/2026 100 P,,1,2.50,0.65,249.35
10/02/2026,Buy to Open,DEMO 11/20/2026 95 P,,1,1.00,0.65,-100.65
10/22/2026,Expired,DEMO 10/22/2026 90 P,,-1,,,
"""


class LedgerTests(unittest.TestCase):
    def report(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.csv"
            path.write_text(content, encoding="utf-8")
            return audit(read_export(path))

    def test_reconciliation_and_adjusted_date(self):
        report = self.report(CSV)
        self.assertEqual(report["net_transaction_cash"], "148.70")
        self.assertEqual(report["missing_amount_source_lines"], [4])
        self.assertEqual(report["adjusted_date_count"], 1)
        self.assertEqual(report["vertical_spread_candidates"], [{
            "effective_date": "2026-10-02",
            "phase": "open",
            "source_lines": [2, 3],
            "net_cash": "148.70",
        }])

    def test_malformed_row_is_reported_and_later_rows_survive(self):
        content = CSV.replace("0.65,-100.65", "0.65,bad")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.csv"
            path.write_text(content, encoding="utf-8")
            warnings = []
            rows = read_export(path, diagnostics=warnings)
        self.assertEqual([row.source_line for row in rows], [2, 4])
        self.assertEqual(warnings, [{"file": "fixture.csv", "line": 3,
                                     "reason": "invalid date or numeric field"}])

    def test_competing_leg_is_ambiguous(self):
        row = "10/02/2026,Buy to Open,DEMO 11/20/2026 90 P,,1,0.50,0.65,-50.65\n"
        report = self.report(CSV + row)
        self.assertEqual(report["vertical_spread_candidates"], [])
        self.assertEqual(report["ambiguous_spread_source_lines"], [2, 3, 5])

    def test_reward_rejects_guesses_and_invalid_answers(self):
        cases = {
            '{"source_lines":[3,2],"net_cash":"148.70"}': 1.0,
            '{"source_lines":[2,4],"net_cash":"148.70"}': 0.0,
            '{"source_lines":[2,3],"net_cash":"148.71"}': 0.0,
            '{"source_lines":[2,3],"net_cash":"NaN"}': 0.0,
            '{"source_lines":[2,3],"net_cash":"148.70","net_cash":"148.70"}': 0.0,
            'not JSON': 0.0,
        }
        for answer, expected in cases.items():
            with self.subTest(answer=answer):
                self.assertEqual(score_spread(answer, [2, 3], "148.70"), expected)

    def test_parenthesized_values_as_of_date_and_identical_rows(self):
        header = CSV.splitlines()[0]
        row = '01/02/2026 as of 12/31/2025,Expired,DEMO 01/16/2026 100 C,,(2),,,(200)'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.csv"
            path.write_text("\n".join((header, row, row)) + "\n", encoding="utf-8")
            diagnostics = []
            rows = read_export(path, diagnostics=diagnostics)
        self.assertEqual(diagnostics, [])
        self.assertEqual([r.source_line for r in rows], [2, 3])
        for parsed in rows:
            self.assertEqual(parsed.quantity, Decimal(-2))
            self.assertEqual(parsed.amount, Decimal(-200))
            self.assertEqual(parsed.posted_date, date(2026, 1, 2))
            self.assertEqual(parsed.effective_date, date(2025, 12, 31))

    def test_mutated_records_are_rejected_and_later_rows_survive(self):
        header, valid, *_ = CSV.splitlines()
        for bad in (valid.replace("10/03/2026", "not-a-date"),
                    valid.replace(",1,2.50", ",bad,2.50"),
                    valid + ",extra"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "fixture.csv"
                path.write_text("\n".join((header, valid, bad, valid)) + "\n", encoding="utf-8")
                diagnostics = []
                self.assertEqual([r.source_line for r in read_export(path, diagnostics=diagnostics)], [2, 4])
                issue, = diagnostics
                self.assertEqual((issue["file"], issue["line"]), (path.name, 3))
                self.assertTrue(issue["reason"])

    def test_missing_or_duplicate_transaction_headers_are_fatal(self):
        header = CSV.splitlines()[0]
        for bad in (header.replace(",Amount", ""), header + ",Amount"):
            with self.subTest(header=bad), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "fixture.csv"
                path.write_text(bad + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Missing or duplicate"):
                    read_export(path, diagnostics=[])
