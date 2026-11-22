import csv
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from ledger import HEADERS, read_export
from period_review import review
from reconcile import holdings_comparison, realized_comparison


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.symbol = "DEMO 02/20/2026 100 C"

    def csv(self, name, rows):
        path = self.root / name
        with path.open("w", newline="", encoding="utf-8") as file:
            csv.writer(file).writerows(rows)
        return path

    def test_december_close_posted_in_january_reconciles_in_both_date_bases(self):
        symbol = self.symbol
        rows = read_export(self.csv("transactions.csv", [
            ["Transaction history"], HEADERS,
            ["02/20/2026", "Expired", symbol, "", "1", "", "", "0"],
            ["01/20/2026", "Cancel Buy to Open", symbol, "", "1", "", "", "100"],
            ["01/02/2026 as of 12/31/2025", "Sell to Close", symbol, "", "1", "", "", "150"],
            ["2025-12-30", "Buy to Open", symbol, "", "2", "", "", "(200)"],
        ]))
        lots = self.csv("realized.csv", [
            ["Symbol", "Closed Date", "Transaction Closed Date", "Opened Date", "Quantity",
             "Proceeds", "Cost Basis (CB)", "Gain/Loss ($)", "Long Term Gain/Loss",
             "Short Term Gain/Loss", "Term", "Wash Sale?", "Disallowed Loss"],
            [symbol, "01/02/2026", "12/31/2025", "12/30/2025", "1",
             "150", "100", "50", "", "50", "Short", "Yes", "5"],
        ])
        group, = realized_comparison(rows, lots, "2025-12")["groups"]
        self.assertEqual(group["status"], "group_ties")
        self.assertEqual(group["transaction_lines"], [5])
        self.assertTrue(group["broker_wash_sale_flag"])
        self.assertEqual(realized_comparison(rows, lots, "2026-01")["groups"], [])
        dec = review(rows, lots, 2025)
        self.assertEqual(dec["monthly"]["2025-12"]["option_close_comparison"]["groups"], [group])
        self.assertEqual(dec["reported_amounts"]["year"]["realized"], Decimal(50))
        self.assertEqual(dec["monthly"]["2025-12"]["reported_amounts"]["realized"], Decimal(50))
        self.assertEqual(dec["broker_lots"][0]["open_evidence"]["status"], "single_row_partial")
        self.assertEqual(review(rows, lots, 2026)["broker_lots"], [])
        jan = review(rows, lots, 2026, date_basis="posted")
        self.assertEqual(jan["reported_amounts"]["year"]["realized"], Decimal(50))
        self.assertEqual(jan["monthly"]["2026-01"]["reported_amounts"]["realized"], Decimal(50))
        self.assertEqual(len(jan["monthly"]["2026-01"]["option_close_comparison"]["groups"]), 1)
        self.assertEqual(review(rows, lots, 2025, date_basis="posted")["broker_lots"], [])
        self.assertIsNone(review([], lots, 2026)["source_scope"]["first_effective"])

    def test_holdings_reports_missing_quantities_without_counting_ties(self):
        symbol = self.symbol
        healthy = "OTHER 02/20/2026 100 P"
        rows = read_export(self.csv("transactions.csv", [
            HEADERS,
            ["01/03/2026", "Unknown", symbol, "", "1", "", "", "0"],
            ["01/03/2026", "Buy to Open", healthy, "", "1", "", "", "-100"],
        ]))
        positions = self.csv("positions.csv", [
            ["Symbol", "Qty (Quantity)"], [symbol, ""], [healthy, "1"],
        ])
        result = holdings_comparison(rows, positions, date(2026, 1, 4))
        issues, = result["unresolved_contracts"].values()
        self.assertEqual([issue["reason"] for issue in issues], ["unsupported_action", "missing_quantity"])
        self.assertEqual(result["contracts_compared"], 1)
        self.assertEqual(result["quantity_ties"], 1)
