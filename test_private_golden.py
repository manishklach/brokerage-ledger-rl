"""Opt-in regression for five consecutive years of local brokerage exports."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from ledger_review import main


class PrivateGoldenTests(unittest.TestCase):
    def test_five_year_private_golden(self):
        directory = Path(os.environ.get("LEDGER_PRIVATE_DIR", Path(__file__).parent / "private"))
        transactions = directory / "transactions.csv"
        realized = directory / "realized.csv"
        expected = directory / "golden-hash.txt"
        if not transactions.is_file() or not realized.is_file():
            self.skipTest("private golden inputs not present")
        if not expected.is_file():
            self.fail("Private exports are present but the pinned golden-hash.txt is missing")
        years = sorted(int(y) for y in os.environ.get("LEDGER_PRIVATE_YEARS", "").split(",") if y.strip())
        self.assertEqual(len(years), 5, "Set LEDGER_PRIVATE_YEARS to five consecutive years")
        self.assertEqual(years, list(range(years[0], years[0] + 5)))
        reports = []
        with tempfile.TemporaryDirectory() as temp:
            for year in years:
                output = Path(temp) / f"ledger-{year}.json"
                code = main([str(transactions), "--realized", str(realized), "--year", str(year),
                             "--date-basis", "effective", "--output", str(output)])
                self.assertIn(code, (0, 1))
                reports.append(json.loads(output.read_text(encoding="utf-8")))
        digest = hashlib.sha256(json.dumps(reports, sort_keys=True).encode()).hexdigest()
        self.assertEqual(digest, expected.read_text(encoding="ascii").strip().lower(),
                         "Private five-year ledger digest changed")
