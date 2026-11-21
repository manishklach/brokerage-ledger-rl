"""Independently labeled synthetic opening-evidence cases for Inkling evaluation."""

import random
from datetime import date, timedelta

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


def expanded_evidence_cases():
    """Generate fixed, balanced cases with labels specified by each scenario."""
    rng = random.Random(260112)
    result = []
    for index in range(8):
        year, month = 2022 + index // 4, 2 + 2 * (index % 4)
        after = date(year, month, 1)
        before = after - timedelta(days=1)
        side = "Buy to Open" if index % 2 == 0 else "Sell to Open"
        opposite = "Sell to Open" if side == "Buy to Open" else "Buy to Open"
        qty = rng.randint(9, 25)
        extra = rng.randint(2, 6)
        scenarios = [
            ("cross-month-partial", "supported", [(before, qty + extra), (after, extra)], [0, 1]),
            ("split-fill-exact", "supported", [(before, qty - 1), (before, 1), (after, extra)], [0, 1, 2]),
            ("competing-partials", "ambiguous", [(before, qty - 1), (before, extra), (after, extra)], []),
            ("competing-full-fills", "ambiguous", [(before, qty), (before, qty), (after, extra)], []),
            ("missing-second-date", "missing_evidence", [(before, qty)], []),
            ("one-contract-short", "missing_evidence", [(before, qty - 1), (after, extra)], []),
        ]
        for offset, (scenario, label, fills, positions) in enumerate(scenarios):
            expiry = (after + timedelta(days=47)).isoformat()
            root = f"SIM{chr(65 + index)}{chr(65 + offset)}"
            strike = 80 + index * 5 + offset
            right = "C" if offset % 2 == 0 else "P"
            contract = f"{root} {expiry} {strike} {right}"
            adjacent = f"{root} {expiry} {strike + 1} {right}"
            ids = rng.sample(range(12, 905), len(fills) + 5)
            rows = [(ids[i], day, contract, side, size) for i, (day, size) in enumerate(fills)]
            noise = [
                (before, contract, opposite, qty), (after, contract, opposite, extra),
                (before, adjacent, side, qty), (after, adjacent, side, extra),
                (after + timedelta(days=2), contract, side, qty + extra),
            ]
            rows.extend((line, *row) for line, row in zip(ids[len(fills):], noise, strict=True))
            rng.shuffle(rows)
            table = "\n".join(" | ".join(map(str, row)) for row in rows)
            prompt = (
                f"The broker attributed a partial close of {contract} to {qty} contracts opened on "
                f"{before} and {extra} on {after}, both as {side}. Check the opening evidence.\n"
                "Count only rows with the exact contract, date, and action. If any date is short, "
                "return missing_evidence. Otherwise, if any date has multiple eligible rows "
                "whose combined quantity exceeds the allocation, return ambiguous. A single "
                "eligible row can cover a partial allocation. Otherwise return supported and cite "
                "all eligible rows. Return JSON with status and source_lines. Use integer row IDs. "
                "For missing_evidence and ambiguous, use an empty source_lines array.\n"
                "Line | Effective date | Contract | Action | Quantity\n" + table
            )
            result.append({
                "id": f"inkling-evidence-{index + 1:02d}-{scenario}",
                "question": prompt,
                "expected_cash": label,
                "expected_lines": sorted(ids[i] for i in positions),
                "scenario": scenario,
                "contract": contract,
                "required_by_date": {str(before): qty, str(after): extra},
                "opening_action": side,
                "rows": rows,
            })
    rng.shuffle(result)
    return result
