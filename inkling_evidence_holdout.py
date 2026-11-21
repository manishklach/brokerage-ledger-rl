"""Independently labeled synthetic opening-evidence cases for Inkling evaluation."""

from lot_pilot_data import evidence_prompt


def evidence_cases():
    buy, sell = "Buy to Open", "Sell to Open"
    cases = [
        ("cross-month-partial", buy, {"2023-08-31": 2, "2023-09-01": 1}, [
            (42, "2023-09-01", buy, 1), (65, "2023-08-31", buy, 5),
            (19, "2023-09-05", buy, 9), (88, "2023-08-31", sell, 2),
        ], "supported", [42, 65]),
        ("multi-row-exact", sell, {"2024-02-29": 15}, [
            (9, "2024-02-29", sell, 8), (255, "2024-02-29", sell, 7),
            (26, "2024-02-28", sell, 15), (47, "2024-02-29", buy, 15),
        ], "supported", [9, 255]),
        ("row-election-unknown", sell, {"2024-10-08": 3}, [
            (39, "2024-10-08", sell, 3), (51, "2024-10-08", sell, 1),
            (53, "2024-10-08", sell, 2), (61, "2024-10-10", sell, 3),
        ], "ambiguous", []),
        ("multiple-candidate-allocations", buy, {"2023-12-29": 1, "2024-01-02": 4}, [
            (301, "2024-01-02", buy, 3), (302, "2024-01-02", buy, 2),
            (320, "2023-12-29", buy, 1), (102, "2024-01-02", sell, 4),
        ], "ambiguous", []),
        ("wrong-side-shortfall", sell, {"2024-07-03": 10}, [
            (27, "2024-07-03", sell, 9), (65, "2024-07-03", buy, 10),
            (90, "2024-07-05", sell, 10),
        ], "missing_evidence", []),
        ("missing-date-with-ambiguous-date", buy, {"2024-09-30": 3, "2024-10-01": 2}, [
            (66, "2024-09-30", buy, 5), (71, "2024-09-30", buy, 3),
            (15, "2024-10-01", sell, 2), (29, "2024-10-02", buy, 2),
        ], "missing_evidence", []),
    ]
    return [
        {"id": name, "expected_cash": status, "expected_lines": lines,
         "question": evidence_prompt(required, [
             {"line": line, "date": day, "action": side, "quantity": qty}
             for line, day, side, qty in records
         ], action)}
        for name, action, required, records, status, lines in cases
    ]
