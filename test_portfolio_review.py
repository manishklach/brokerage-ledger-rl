import unittest
from datetime import date
from decimal import Decimal

from ledger import Transaction
from portfolio_review import build_portfolio_report


class PortfolioReportTest(unittest.TestCase):
    def test_normalized_option_rows_reconcile_without_broker_csv(self):
        opened = date(2025, 1, 2)
        closed = date(2025, 1, 6)
        symbol = "XYZ 2025-02-21 100 C"
        transactions = [
            Transaction(2, opened, opened, "Buy to Open", symbol, "",
                        Decimal(1), Decimal(1), Decimal(0), Decimal(-100)),
            Transaction(3, closed, closed, "Sell to Close", symbol, "",
                        Decimal(1), Decimal(2), Decimal(0), Decimal(200)),
        ]
        lot = {
            "broker_source_line": 5, "underlying": "XYZ", "instrument": symbol,
            "is_option": True, "quantity": Decimal(1), "opened": opened.isoformat(),
            "closed": closed.isoformat(), "transaction_closed": closed.isoformat(),
            "term": "Short Term", "wash_sale_flag": False, "proceeds": Decimal(200),
            "broker_basis": Decimal(100), "realized": Decimal(100),
            "short_term": Decimal(100), "long_term": Decimal(0),
            "disallowed_loss_reported": Decimal(0),
        }
        position = {
            "source_line": 7, "symbol": "XYZ", "underlying": "XYZ", "kind": "Equity",
            "quantity": Decimal(2), "market_value": Decimal(250),
            "unrealized": Decimal(20), "is_option": False,
        }

        report = build_portfolio_report(transactions, [lot], [position], closed, closed, ["XYZ"])

        monthly = report["monthly"]
        self.assertEqual(monthly["realized"]["realized"], Decimal(100))
        groups = monthly["monthly_transaction_review"]["option_close_comparison"]["groups"]
        self.assertEqual(groups[0]["status"], "group_ties")
        self.assertEqual(groups[0]["broker_lines"], [5])
        self.assertEqual(groups[0]["transaction_lines"], [3])
        self.assertEqual(report["holdings"]["ranked_marks"][0]["source_lines"], [7])
        self.assertNotIn("close_evidence", lot)
