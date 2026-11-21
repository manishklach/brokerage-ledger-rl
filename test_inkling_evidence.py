import json
import unittest
from collections import Counter

from evaluate_portfolio_server import score_lot
from inkling_evidence_holdout import evidence_cases, expanded_evidence_cases
from lot_pilot_data import classify


class InklingEvidenceTests(unittest.TestCase):
    def test_exact_integer_citations_and_unique_fields(self):
        case = evidence_cases()[0]
        self.assertTrue(score_lot('{"status":"supported","source_lines":[65,42]}', case))
        self.assertFalse(score_lot('{"status":"supported","source_lines":["42","65"]}', case))
        self.assertFalse(score_lot('{"status":"ambiguous","status":"supported","source_lines":[42,65]}', case))

    def test_holdout_has_independent_labels_for_each_status(self):
        cases = evidence_cases()
        self.assertEqual({case["expected_cash"] for case in cases},
                         {"supported", "ambiguous", "missing_evidence"})
        for case in cases:
            response = json.dumps({"status": case["expected_cash"], "source_lines": case["expected_lines"]})
            self.assertTrue(score_lot(response, case))

    def test_expanded_holdout_matches_independent_quantity_verifier(self):
        cases = expanded_evidence_cases()
        self.assertEqual(len({case["contract"] for case in cases}), 48)
        self.assertEqual(Counter(case["expected_cash"] for case in cases),
                         {"supported": 16, "ambiguous": 16, "missing_evidence": 16})
        for case in cases:
            rows = [{"line": line, "date": str(day), "action": action, "quantity": qty}
                    for line, day, contract, action, qty in case["rows"] if contract == case["contract"]]
            with self.subTest(case=case["id"]):
                self.assertEqual(classify(case["required_by_date"], rows, case["opening_action"]),
                                 (case["expected_cash"], case["expected_lines"]))
