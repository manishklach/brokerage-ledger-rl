"""Synthetic portfolio intent routing with separately worded training and test prompts."""

import json
import random

from rewards import unique_fields

INTENTS = {
    "rank_exposure": ("rank my exposures by underlying", "rank underlyings by absolute signed marked value",
                      "Which symbols dominate my book by net marked value?", "List the biggest sleeves, grouped by underlying."),
    "concentration": ("calculate concentration for TQQQ SOXL and XLK and compare delta adjustment", "show the share of gross exposure in my three ETFs and their delta ranking",
                      "What fraction of the book belongs to TQQQ, SOXL and XLK combined?", "How concentrated am I in the three ETF sleeves by mark and by delta?"),
    "gross_net": ("give gross and net market exposure across my ETF positions", "show long and short marks and their net offsets",
                  "Break down signed exposure versus total absolute marks for the ETFs.", "Where do long and short positions offset each other?"),
    "realized_unrealized": ("compare monthly realized P&L with snapshot unrealized P&L", "rank drivers of realized and unrealized returns",
                            "What did I actually make this month versus what is still on paper?", "Which names drove booked gains and current paper gains?"),
    "expiration_windows": ("count options expiring within 7 30 and 90 days", "show upcoming expirations by time bucket",
                           "How much expires this week, this month and this quarter?", "Where are my near-term expiry clusters by option quantity and marked value?"),
    "portfolio_stress": ("stress TQQQ SOXL and XLK with a five percent spot drop and five volatility points up", "estimate the portfolio drawdown when all three underlyings drop and volatility jumps",
                         "Reprice the three ETF sleeves with spots down 5% and IV up five points.", "What's the book's modeled loss under a simultaneous ETF drop and volatility shock?"),
    "assignment_exposure": ("rank short options by potential assignment cash and share exposure", "screen all short options for the largest assignment obligations",
                            "Which written contracts could require the most shares or cash?", "Across the three ETFs, what short positions carry the biggest exercise settlement exposure?"),
    "fund_overlap": ("compare common holdings and risk factors across TQQQ SOXL and XLK", "show sector overlap and correlation among the ETFs",
                     "Are these three funds effectively giving me the same bets?", "Check whether my ETF sleeves move together or diversify each other."),
    "cash_buying_power": ("show available cash buying power and coverage of near term assignments", "compare available liquidity and purchasing power to simultaneous assignments",
                         "Would settled cash cover my near-term assignment screen, and what buying power is reported?", "What's my available cash and buying power if several written options get assigned?"),
    "positions": ("list my shares and options by ticker expiry strike right and signed quantity", "show all current TQQQ SOXL and XLK positions",
                  "What contracts and shares are in each of my ETF sleeves right now?", "Inventory my holdings with signed sizes and contract details."),
    "entry_vs_mark": ("compare entry cash including fees with current mark on my largest TQQQ option", "show what I paid or received at entry and the position market value now",
                      "For my biggest TQQQ option, what was the opening credit or debit versus its mark?", "How does today's value of my largest TQQQ contract compare with my opening outlay?"),
    "spread_payoff": ("calculate SOXL spread breakeven and maximum gain and loss", "show the expiration payoff limits and breakeven on my spread",
                      "Where does my SOXL spread break even and how far can it win or lose at expiry?", "What are the best and worst terminal outcomes for the SOXL spread?"),
    "position_stress": ("estimate P&L if the underlying of my largest XLK option moves five percent", "stress one XLK position with up and down price scenarios before expiry",
                        "What would a five percent swing in XLK do to my biggest option before expiration?", "Show up and down scenario P&L for one XLK contract."),
    "spread_assignment": ("simulate assignment on the short leg of a SOXL spread", "show the share delivery cash and remaining legs if the short spread leg is assigned",
                          "If my SOXL short leg is exercised early, what is left in the spread?", "What happens to shares and cash if the short side of this spread is assigned?"),
    "partial_close": ("show broker-matched opening lots realized P&L and remainder after an XLK partial close", "reconcile the partially closed XLK position and remaining contracts",
                      "I exited only part of the XLK trade. Which lots were closed and what remains?", "Which XLK opening lots did Schwab use when I trimmed the position?"),
    "roll": ("find a TQQQ roll and show closing and opening legs, cash and realized P&L", "link the old and new TQQQ contracts and compute credit or debit of the roll",
             "Did I replace an existing TQQQ contract with a new one, and what did it cost?", "Show the outgoing and replacement legs of any TQQQ roll."),
    "opening_evidence": ("check recorded opening fills against Schwab allocation for a September XLK close", "verify opening evidence for the broker-matched XLK lots",
                         "Are there enough source fills to back up the broker's September XLK opening-lot allocation?", "Does the transaction history support Schwab's reported open dates and quantities on the XLK exit?"),
    "bid_ask": ("compare option P&L at the bid and ask versus the displayed mark", "mark the largest TQQQ contract at bid and offer and show the P&L range",
               "What would my largest TQQQ option P&L show at either side of the spread?", "How far does the displayed option P&L move if I use the bid or offer instead of the mark?"),
    "tax_terms": ("summarize broker-reported short and long term gains by TQQQ SOXL and XLK", "split the tax report realized amounts into long-term and short-term buckets",
                   "How much did Schwab classify as long-term versus short-term for the three ETFs?", "Show the term breakdown of broker-reported realized gains for the tax year."),
    "wash_sales": ("find broker wash sale flags and disallowed losses and link replacement lots", "check reported wash adjustments and possible replacement shares",
                   "Which flagged losses did Schwab disallow, and can we trace the replacement purchases?", "Show the wash-sale amounts the broker reported and any verified replacement lot."),
    "clarify": ("show the details of that trade without stating which trade or what details", "tell me how the thing in my account is doing without specifying an analysis",
                "Can you check that position for me?", "How did that one go?"),
    "unsupported": ("submit an order to buy shares now", "move money out of my brokerage account",
                    "Sell all my XLK shares immediately.", "Wire money from Schwab to my bank."),
}


def score_route(reply, _lines, expected):
    try:
        answer = json.loads(reply, object_pairs_hook=unique_fields)
    except ValueError:
        return 0.0
    return float(answer == {"query": expected})


def routing_cases(split, count):
    definitions = "\n".join(f"{name}: {phrases[0]}" for name, phrases in INTENTS.items())
    examples = []
    for name, phrases in INTENTS.items():
        if split == "train":
            questions = [frame.format(phrase=phrase) for phrase in phrases[:2] for frame in (
                "{phrase}.", "Please {phrase}.", "For my Schwab account, {phrase}.",
                "Could you {phrase}?", "I'd like you to {phrase}.", "Can we {phrase}?",
            )]
        elif split == "eval":
            questions = phrases[2:]
        else:
            raise ValueError("Unknown split")
        for question in questions:
            examples.append({
                "question": "Choose one portfolio query for the user's question. "
                            "Use clarify for underspecified requests and unsupported for requests "
                            "outside the read-only workflow. Return only JSON with the key query.\n"
                            f"{definitions}\nUser question: {question}",
                "expected_cash": name, "expected_lines": [],
                "answer": json.dumps({"query": name}),
            })
    random.Random(1991 if split == "train" else 1992).shuffle(examples)
    return examples[:count]
