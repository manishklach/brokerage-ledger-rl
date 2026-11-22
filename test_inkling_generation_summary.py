import unittest

from summarize_inkling_generation import summarize


class InklingGenerationSummaryTest(unittest.TestCase):
    def test_unsupported_and_unpaired_rows_do_not_change_supported_accuracy(self):
        def reply(case, variant, target, prediction, correct):
            return dict(case=case, variant=variant, target=target,
                        predicted_status=prediction, correct=correct, truncated=False)

        score = summarize([
            reply(1, "stock", "supported", "supported", 1),
            reply(1, "step12", "supported", "supported", 1),
            reply(2, "stock", "missing_evidence", "supported", 0),
            reply(2, "step12", "missing_evidence", "missing_evidence", 1),
            reply(3, "stock", "supported", "supported", 0),
        ])
        self.assertEqual(score["supported_both_correct_rate"], 1.0)
        self.assertEqual(score["incomplete_cases"], 1)
        unsupported = score["groups"]["unsupported"]
        self.assertEqual(unsupported["both_correct_rate"], 0.0)
        self.assertEqual(unsupported["stock"]["false_support_rate"], 1.0)
        self.assertEqual(unsupported["step12"]["status_recall"], {"missing_evidence": 1.0})
