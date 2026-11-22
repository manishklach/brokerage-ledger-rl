import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from ledger import Transaction
from option_lots import match_options


class OptionLotTests(unittest.TestCase):
    def row(self, line, day, action, qty, amount):
        return Transaction(line, day, day, action, "DEMO 11/20/2026 100 C", "",
                           Decimal(qty), None, None, Decimal(amount))

    def test_prior_close_consumes_inventory_and_partial_cost_ties(self):
        sept = date(2026, 9, 1)
        oct_ = date(2026, 10, 1)
        rows = [
            self.row(2, oct_, "Sell to Close", 3, "45.00"),
            self.row(3, sept, "Sell to Close", 1, "15.00"),
            self.row(4, sept, "Buy to Open", 1, "-8.99"),
            self.row(5, sept, "Buy to Open", 3, "-30.01"),
        ]
        result, = match_options(rows, "2026-10")["closes"]
        self.assertEqual(result["provisional_pnl"], "16.00")
        self.assertEqual([m["open_line"] for m in result["matches"]], [5, 4])
        self.assertEqual([m["open_cash"] for m in result["matches"]], ["-20.01", "-8.99"])

    def test_cancellation_blocks_estimate(self):
        day = date(2026, 10, 1)
        rows = [
            self.row(2, day, "Sell to Close", 1, "15"),
            self.row(3, day, "Cancel Buy to Open", 1, "10"),
            self.row(4, day, "Buy to Open", 1, "-10"),
        ]
        result, = match_options(rows, "2026-10")["closes"]
        self.assertIsNone(result["provisional_pnl"])
        self.assertEqual(result["blocking_lines"], [3])

    def test_partial_coverage_has_no_whole_close_pnl(self):
        day = date(2026, 10, 1)
        rows = [
            self.row(2, day, "Buy to Close", 2, "-20"),
            self.row(3, day, "Sell to Open", 1, "15"),
        ]
        result, = match_options(rows, "2026-10")["closes"]
        self.assertEqual(result["unmatched_quantity"], "1")
        self.assertIsNone(result["provisional_pnl"])

    def test_full_assignment_leaves_clean_inventory_for_later_round_trip(self):
        day = date(2026, 10, 1)
        rows = [
            self.row(5, day, "Sell to Open", 2, "80"),
            self.row(4, day, "Assigned", 2, "0"),
            self.row(3, day, "Sell to Open", 1, "20"),
            self.row(2, day, "Buy to Close", 1, "-13"),
        ]
        close, = match_options(rows, "2026-10")["closes"]
        self.assertEqual(close["provisional_pnl"], "7.00")
        self.assertEqual(close["matches"][0]["open_line"], 3)

    def test_partial_assignment_blocks_only_affected_side(self):
        day = date(2026, 10, 1)
        rows = [
            self.row(8, day, "Sell to Open", 2, "80"),
            self.row(9, day, "Sell to Open", 1, "30"),
            self.row(7, day, "Assigned", 1, "0"),
            self.row(6, day, "Buy to Open", 1, "-10"),
            self.row(5, day, "Buy to Close", 1, "-13"),
            self.row(4, day, "Sell to Close", 1, "15"),
        ]
        long_close, short_close = match_options(rows, "2026-10")["closes"]
        self.assertEqual(long_close["provisional_pnl"], "5.00")
        self.assertEqual(short_close["blocking_lines"], [7])

    def test_partial_assignment_consumes_unambiguous_lot_with_exact_remainder(self):
        day = date(2026, 10, 1)
        rows = [
            self.row(4, day, "Sell to Open", 3, "10"),
            self.row(3, day, "Assigned", 1, "0"),
            self.row(2, day, "Buy to Close", 2, "-5"),
        ]
        for newest_first in (False, True):
            close, = match_options(rows, "2026-10", newest_first=newest_first)["closes"]
            match, = close["matches"]
            self.assertEqual(match["open_cash"], "6.67")
            self.assertEqual(match["prior_settlement_lines"], [3])
            self.assertEqual(close["provisional_pnl"], "1.67")

    def test_reports_both_month_bases(self):
        day = date(2026, 9, 30)
        close = replace(self.row(2, day, "Sell to Close", 1, "15"), posted_date=date(2026, 10, 1))
        rows = [close, self.row(3, day, "Buy to Open", 1, "-10")]
        self.assertEqual(len(match_options(rows, "2026-10", date_basis="posted")["closes"]), 1)
        self.assertEqual(match_options(rows, "2026-10")["closes"], [])
        result, = match_options(rows, "2026-09")["closes"]
        self.assertEqual(result["provisional_pnl"], "5.00")
