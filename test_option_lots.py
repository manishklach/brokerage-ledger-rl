import random
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from ledger import Transaction, cash_total
from option_lots import match_options
from period_review import review_lots


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

    def test_partial_assignment_uses_fifo_across_open_lots(self):
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
        self.assertEqual(short_close["provisional_pnl"], "27.00")
        event, = match_options(rows, "2026-10")["other_option_events"]
        self.assertEqual(event["allocations"], [{"open_line": 9, "quantity": "1", "open_cash": "30.00"}])

    def test_partial_settlement_spans_multiple_lots_and_quarantines_unknown_event(self):
        day = date(2026, 10, 1)
        rows = [
            self.row(6, day, "Buy to Open", 3, "-30"),
            self.row(5, day, "Buy to Open", 5, "-100"),
            self.row(4, day, "Exchange or Exercise", -4, "0"),
            self.row(3, day, "Unknown Adjustment", 1, "0"),
            self.row(2, day, "Sell to Close", 4, "120"),
        ]
        report = match_options(rows, "2026-10")
        close, = report["closes"]
        self.assertEqual(close["provisional_pnl"], "40.00")
        self.assertEqual(close["quarantined_event_lines"], [3])
        self.assertEqual(close["matches"][0]["prior_settlement_basis"], "fifo")
        event = report["other_option_events"][1]
        self.assertEqual([row["quantity"] for row in event["allocations"]], ["3", "1"])
        issue, = report["unresolved_contracts"][close["contract"]]
        self.assertEqual(issue["reason"], "unsupported_option_event")
        self.assertIsNone(issue["side"])

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

    def test_seeded_partial_settlements_conserve_quantity_and_open_cash(self):
        rng = random.Random(20261122)
        day = date(2026, 10, 1)
        for _ in range(200):
            sizes = [rng.randint(1, 10) for _ in range(2)]
            amounts = [Decimal(-rng.randint(100, 5000)) / 100 for _ in sizes]
            settled = rng.randint(1, sum(sizes) - 1)
            rows = [self.row(5, day, "Buy to Open", sizes[0], amounts[0]),
                    self.row(4, day, "Buy to Open", sizes[1], amounts[1]),
                    self.row(3, day, rng.choice(("Expired", "Assigned", "Exchange or Exercise")), -settled, "0"),
                    self.row(2, day, "Sell to Close", sum(sizes) - settled, "101.25")]
            result = match_options(rows, None)
            settlement, = result["other_option_events"]
            close, = result["closes"]
            allocations = settlement["allocations"] + close["matches"]
            self.assertEqual(sum(int(row["quantity"]) for row in allocations), sum(sizes))
            self.assertEqual(sum(Decimal(row["open_cash"]) for row in allocations), sum(amounts))
            self.assertEqual(sum(Decimal(row["close_cash"]) for row in close["matches"]), Decimal("101.25"))
            self.assertEqual(close["unmatched_quantity"], "0")

    def test_seeded_short_side_settlements_conserve_quantity_and_open_cash(self):
        rng = random.Random(20261123)
        day = date(2026, 10, 1)
        actions = ("Expired", "Assigned", "Exchange or Exercise")
        for trial in range(200):
            sizes = [rng.randint(1, 10) for _ in range(2)]
            amounts = [Decimal(rng.randint(100, 5000)) / 100 for _ in sizes]
            available = sum(sizes)
            settled = rng.randint(1, available - 1)
            rows = [
                self.row(6, day, "Sell to Open", sizes[0], amounts[0]),
                self.row(5, day, "Sell to Open", sizes[1], amounts[1]),
                self.row(4, day, actions[trial % len(actions)], settled, 0),
                self.row(3, day, "Buy to Close", available - settled, "-101.25"),
                self.row(2, day, "Buy to Close", 1, "-1"),
            ]
            report = match_options(rows, None)
            probe, close = report["closes"]
            settlement, = report["other_option_events"]
            allocations = settlement["allocations"] + close["matches"]
            self.assertEqual(sum(int(row["quantity"]) for row in allocations), available)
            self.assertEqual(sum(Decimal(row["open_cash"]) for row in allocations), sum(amounts))
            self.assertEqual(sum(Decimal(row["close_cash"]) for row in close["matches"]), Decimal("-101.25"))
            self.assertEqual(close["unmatched_quantity"], "0")
            self.assertEqual(probe["unmatched_quantity"], "1")
            self.assertEqual(probe["matches"], [])

    def test_seeded_partial_fills_conserve_cash_across_closes(self):
        rng = random.Random(20261124)
        day = date(2026, 10, 1)
        for _ in range(200):
            quantity = rng.randint(2, 25)
            first_fill = rng.randint(1, quantity - 1)
            amounts = [Decimal(rng.randint(100, 5000)) / 100 for _ in range(3)]
            rows = [self.row(4, day, "Buy to Open", quantity, -amounts[0]),
                    self.row(3, day + timedelta(days=1), "Sell to Close", first_fill, amounts[1]),
                    self.row(2, day + timedelta(days=2), "Sell to Close", quantity - first_fill, amounts[2])]
            closes = match_options(rows, None)["closes"]
            matches = [row for close in closes for row in close["matches"]]
            self.assertEqual(sum(int(row["quantity"]) for row in matches), quantity)
            self.assertEqual(sum(Decimal(row["open_cash"]) for row in matches), -amounts[0])
            for close in closes:
                self.assertEqual(close["unmatched_quantity"], "0")
                self.assertEqual(Decimal(close["provisional_pnl"]),
                                 sum(Decimal(row["open_cash"]) + Decimal(row["close_cash"])
                                     for row in close["matches"]))
            self.assertEqual(sum(Decimal(close["provisional_pnl"]) for close in closes), cash_total(rows))

    def test_seeded_roll_conserves_cash_per_contract(self):
        rng = random.Random(20261125)
        day = date(2026, 10, 1)
        for _ in range(200):
            quantities = [rng.randint(1, 10) for _ in range(2)]
            cash = [Decimal(rng.randint(100, 5000)) / 100 for _ in range(4)]
            rows = [self.row(5, day, "Buy to Open", quantities[0], -cash[0]),
                    self.row(4, day + timedelta(days=1), "Sell to Close", quantities[0], cash[1]),
                    replace(self.row(3, day + timedelta(days=1), "Buy to Open", quantities[1], -cash[2]),
                            symbol="DEMO 12/18/2026 105 C"),
                    replace(self.row(2, day + timedelta(days=2), "Sell to Close", quantities[1], cash[3]),
                            symbol="DEMO 12/18/2026 105 C")]
            later, earlier = match_options(rows, None)["closes"]
            for close, opening, closing in ((earlier, rows[0], rows[1]), (later, rows[2], rows[3])):
                lot, = close["matches"]
                self.assertEqual(lot["open_line"], opening.source_line)
                self.assertEqual(Decimal(lot["quantity"]), opening.quantity)
                self.assertEqual(Decimal(lot["open_cash"]), opening.amount)
                self.assertEqual(Decimal(lot["close_cash"]), closing.amount)
                self.assertEqual(close["unmatched_quantity"], "0")
            self.assertEqual(sum(Decimal(c["provisional_pnl"]) for c in (earlier, later)), cash_total(rows))
            self.assertEqual(rows[1].amount + rows[2].amount, cash[1] - cash[2])

    def test_wash_flagged_lot_cash_excludes_disallowed_loss(self):
        rng = random.Random(20261126)
        day = date(2026, 10, 1)
        for _ in range(200):
            proceeds, basis, adjustment = [Decimal(rng.randint(100, 5000)) / 100 for _ in range(3)]
            flagged = rng.choice((True, False))
            if flagged:
                basis = proceeds + adjustment + Decimal("0.01")
            rows = [self.row(3, day, "Buy to Open", 1, -basis),
                    self.row(2, day + timedelta(days=1), "Sell to Close", 1, proceeds)]
            disallowed = adjustment if flagged else Decimal(0)
            realized = proceeds - basis + disallowed
            lots = [{
                "instrument": "DEMO 2026-11-20 100 C", "underlying": "DEMO",
                "opened": "2026-10-01", "closed": "2026-10-02",
                "transaction_closed": "2026-10-02", "quantity": Decimal(1),
                "broker_source_line": 2, "is_option": True, "term": "short",
                "wash_sale_flag": flagged, "disallowed_loss_reported": disallowed,
                "proceeds": proceeds, "broker_basis": basis, "realized": realized,
                "short_term": realized, "long_term": Decimal(0),
            }]
            report = review_lots(rows, lots, 2026)
            self.assertEqual(report["reported_wash_sale_lots"], int(flagged))
            self.assertEqual(report["broker_control_checks"].get("gain_difference_matches_reported_disallowed_loss", []),
                             [2] if flagged else [])
            self.assertEqual(report["reported_amounts"]["year"]["disallowed_loss_reported"], disallowed)
            self.assertEqual(report["monthly"]["2026-10"]["net_transaction_cash"], proceeds - basis)
            close, = match_options(rows, None)["closes"]
            self.assertEqual(Decimal(close["provisional_pnl"]), proceeds - basis)
            self.assertEqual(close["unmatched_quantity"], "0")

    def test_full_long_settlement_allows_later_round_trip(self):
        day = date(2026, 10, 1)
        rows = [self.row(5, day, "Buy to Open", 2, "-40"),
                self.row(4, day, "Expired", -2, 0),
                self.row(3, day, "Buy to Open", 1, "-15"),
                self.row(2, day, "Sell to Close", 1, "20")]
        close, = match_options(rows, None)["closes"]
        self.assertEqual(close["matches"][0]["open_line"], 3)
        self.assertEqual(close["provisional_pnl"], "5.00")
