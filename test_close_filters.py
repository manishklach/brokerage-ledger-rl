import json
import unittest

from close_filters import parse_filters, resolve


class CloseFilterTests(unittest.TestCase):
    def setUp(self):
        self.case = {
            "id": "close-6", "contract": "DEMO 2030-05-17 115 C",
            "month": "2030-04", "close_lines": [6, 7],
            "evidence_input": {"action": "Buy to Open", "required_by_date": {"2030-04-01": "2"},
                               "rows": [{"line": 19, "date": "2030-04-01",
                                         "action": "Buy to Open", "quantity": "2"}]},
        }
        self.filters = dict(ticker="demo", expiry="2030-05-17", strike="115.00", right="C",
                            month=None, source_line=None)

    def test_close_month_and_source_line(self):
        second = {**self.case, "id": "close-8", "close_lines": [8], "month": "2030-05"}
        index = [self.case, second]
        self.assertEqual(resolve(json.dumps(self.filters), index)["operation"], "clarify")
        self.assertEqual(resolve(json.dumps({**self.filters, "month": "2030-03"}), index)["operation"], "no_match")
        result = resolve(json.dumps({**self.filters, "source_line": 7}), index)
        self.assertEqual(result["close_id"], "close-6")
        self.assertEqual(result["ledger"]["source_lines"], [19])

    def test_invalid_filters_cannot_select_a_close(self):
        for patch in ({"source_line": True}, {"month": "2030-13"}, {"strike": "NaN"},
                      {"expiry": "2030-02-30"}, {"right": "put"}):
            with self.subTest(patch=patch):
                self.assertIsNone(parse_filters(json.dumps({**self.filters, **patch})))
