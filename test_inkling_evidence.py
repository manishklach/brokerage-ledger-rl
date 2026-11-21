import json
import unittest

from evaluate_portfolio_server import score_lot
from inkling_evidence_holdout import evidence_cases


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
