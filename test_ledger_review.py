"""Regression checks for the installed ledger-review command contract."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ledger_review import main

FIXTURE = """Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount
01/02/2026 as of 12/31/2025,Sell to Close,DEMO 02/20/2026 100 C,,1,,,150
12/30/2025,Buy to Open,DEMO 02/20/2026 100 C,,1,,,(100)
"""


GOLDEN_DIGEST = "b36054cf8561b60dba36b26f39304c55251d6457906baf4fb20562ee330e5eee"


class LedgerReviewTests(unittest.TestCase):
    @patch("ledger_review.version", return_value="test")
    def test_report_golden_digest_and_input_protection(self, _):
        with tempfile.TemporaryDirectory() as directory:
            src = Path(directory) / "transactions.csv"
            dst = Path(directory) / "report.json"
            src.write_bytes(FIXTURE.encode())
            self.assertEqual(main([str(src), "--output", str(dst)]), 0)
            report = json.loads(dst.read_text())
            digest = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
            self.assertEqual(digest, GOLDEN_DIGEST)
            self.assertEqual(src.read_bytes(), FIXTURE.encode())

    @patch("ledger_review.version", return_value="test")
    def test_warning_and_protected_output_exit_codes(self, _):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src = root / "transactions.csv"
            src.write_text(FIXTURE + "01/04/2026,Buy,DEMO,,1,,,bogus\n", encoding="utf-8")
            dst = root / "report.json"
            self.assertEqual(main([str(src), "--output", str(dst)]), 1)
            report = json.loads(dst.read_text())
            self.assertEqual(report["audit"]["inputs"][0]["rejected_rows"], 1)
            with self.assertRaises(SystemExit) as error:
                main([str(src), "--output", str(root / "private" / "report.json")])
            self.assertEqual(error.exception.code, 2)
            self.assertFalse((root / "private").exists())

    @patch("ledger_review.version", return_value="test")
    def test_one_cent_change_changes_golden_digest(self, _):
        for original, changed, pnl in (
            (",,,150", ",,,150.01", "50.01"),
            ("(100)", "(100.01)", "49.99"),
            (",1,,,(100)", ",2,,,(100)", "100.00"),
        ):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                src = Path(directory) / "transactions.csv"
                dst = Path(directory) / "report.json"
                src.write_bytes(FIXTURE.replace(original, changed).encode())
                self.assertEqual(main([str(src), "--output", str(dst)]), 0)
                report = json.loads(dst.read_text())
                digest = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
                self.assertNotEqual(digest, GOLDEN_DIGEST)
                close, = report["options"]["closes"]
                self.assertEqual(close["provisional_pnl"], pnl)
