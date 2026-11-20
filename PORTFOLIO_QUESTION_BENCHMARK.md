# TQQQ, SOXL, and XLK question benchmark

This benchmark tests portfolio analysis, position analysis, and the ability to
answer from brokerage records. Each question has a pass condition and a
minimum set of inputs. Use the portfolio snapshot date for holdings and an
explicit reporting period for realized trades. Dollar totals should reconcile
to the source fields used, with assumptions shown alongside estimates.

## Portfolio and risk

| # | Question | What a passing answer shows | Inputs |
| --- | --- | --- | --- |
| 1 | What are my largest exposures when you group shares and options by underlying? Where do TQQQ, SOXL, and XLK rank? | Rank across the account by absolute marked value. Show signed value and separate shares from options. | Holdings with marks |
| 2 | What share of my open exposure sits in TQQQ, SOXL, and XLK combined? How does the ranking change when options are delta-adjusted? | State the gross denominator and show the marked-value and delta-adjusted calculations separately. | Holdings, underlying prices, option deltas, contract multipliers |
| 3 | What are my gross and net exposures in TQQQ, SOXL, and XLK? Where do the legs offset? | Show positive and negative exposures by underlying on the same measurement basis and identify residual exposure. | Holdings and marks, plus deltas and spots for directional exposure |
| 4 | What drove my realized P&L this month and unrealized P&L at the snapshot? How much came from TQQQ, SOXL, and XLK? | Rank contributors and reconcile realized and unrealized totals separately. State the date range and snapshot timestamp. | Realized detail and holdings with basis or reported unrealized P&L |
| 5 | How much of my options book expires in the next 7, 30, and 90 days? Which expiry matters most for TQQQ, SOXL, or XLK? | State whether the windows are cumulative. Show long and short contract counts and a clearly named exposure metric. | Holdings, expiry dates, and marks or sensitivities for the chosen metric |
| 6 | If TQQQ, SOXL, and XLK each drop 5% and implied volatility rises five points, what is the estimated impact on the three sleeves? | Show each sleeve's change, the aggregate, valuation date, and repricing assumptions. | Positions, spot and option marks, volatility inputs, multipliers, pricing model or adequate Greeks |
| 7 | Which short TQQQ, SOXL, or XLK contracts could create the largest cash or share obligations if assigned? | Show the contract, maximum assigned quantity under the stated scenario, cash direction, and shares delivered or received. | Signed holdings and confirmed deliverables |
| 8 | Do TQQQ, SOXL, and XLK give me distinct exposures, or do they respond to some of the same moves? | Identify overlap using dated fund holdings or return history. Tie the analysis back to this account's exposure. | Portfolio positions and dated fund holdings or comparable return series |
| 9 | How much cash and buying power did Schwab report, and could simultaneous near-term assignments in these three names exceed that cash? | Show reported cash and buying power separately. Compare documented cash with modeled assignment obligations and label any broker-margin uncertainty. | Balances, holdings, deliverables, and broker margin inputs for buying-power changes |

## Positions and trades

| # | Question | What a passing answer shows | Inputs |
| --- | --- | --- | --- |
| 10 | What do I hold in TQQQ, SOXL, and XLK on the snapshot date? List shares and each option contract by expiry, strike, right, and signed quantity. | Match the holdings rows and report a zero or absent share position at the snapshot when supported by the export. | Holdings snapshot |
| 11 | For my largest open TQQQ option position by absolute marked value, what did I pay or collect to open it, including fees, and what is it worth at the snapshot? | Identify the selected contract and distinguish original trade cash from the snapshot mark. Trace the opening amount to lots or source rows. | Holdings and sufficient opening trade history |
| 12 | What are the expiration breakeven, maximum gain, and maximum loss on my SOXL spread? | Identify the legs and entry debit or credit. Ask which spread if pairing is ambiguous. Give the expiration payoff under the stated grouping. | Confirmed spread legs, entry cash, and deliverables |
| 13 | If my largest XLK option position by absolute marked value moves with XLK 5% up or down before expiry, what is its estimated P&L? | Show both scenarios for the same chosen contract and state the time horizon and implied-volatility assumption. | Current trade, spot, marks, and pricing inputs |
| 14 | If the short leg of my SOXL spread is assigned before expiration, what cash and shares move, and what legs remain? | Identify the short leg and show the hypothetical exercise settlement and resulting holdings. Ask for the intended spread if several fit. | Confirmed legs, signed quantities, and deliverables |
| 15 | For my most recent partially closed XLK option, which opening lots did Schwab match, what gain or loss did it report, and how much is still open? | Trace the close to broker lot detail and separate reported realized P&L from verified remaining quantity. | Realized details, sufficient transaction history, and holdings |
| 16 | Did I roll a TQQQ option during the reporting period? Show the close, the new opening leg, the roll cash flow, and the realized P&L on the close. | Show source rows and order-link evidence. Report merely a candidate where the records leave the relationship uncertain. | Transactions, realized details, and order confirmations for a confirmed roll |
| 17 | Find my XLK option close in September 2026. Does the opening history support Schwab's lot allocation? | Ask which close if several match. Once identified, show required and recorded quantities, source rows, and gaps by date. | Close index, recorded openings, and broker-reported lot claim |
| 18 | How much would the displayed P&L of my largest open TQQQ option change if it were marked at the bid or ask? | Show timestamped bid, ask, current mark, and the P&L range. Identify the quote fields if missing. | Holdings basis and timestamped bid/ask/mark |

## Tax reporting

These questions test source reconciliation and how the assistant handles
incomplete tax evidence. Answers should describe what the provided broker
records show and identify gaps before drawing broader conclusions.

| # | Question | What a passing answer shows | Inputs |
| --- | --- | --- | --- |
| 19 | For the reporting period, how much realized gain or loss did Schwab report on TQQQ, SOXL, and XLK, split into short-term and long-term amounts? | Reconcile broker-reported values by underlying and term. Show separately any basis adjustments the export reports and avoid counting both lot rows and group subtotals. | Realized detail and relevant broker tax forms if available |
| 20 | Which realized loss lots on TQQQ, SOXL, or XLK did Schwab flag as wash sales, and what disallowed losses did it report? Can we link each flag to a replacement lot? | Tie amounts to broker rows, distinguish confirmed links from unresolved ones, and state whether the supplied history covers the relevant accounts and dates. | Realized detail, transaction history, and replacement-lot or adjusted-basis evidence |

## How to score

- **2 points:** The answer, units, dates, and source rows reconcile. A precise
  clarification or missing-data response can also earn full credit when the
  supplied evidence calls for one.
- **1 point:** The response identifies the correct position, range, or source,
  but leaves an auditable part of the question unanswered.
- **0 points:** The response selects the wrong position, asserts unsupported
  facts, guesses a missing input, or proceeds despite unresolved ambiguity.

Record the outcome by question ID and distinguish **answered**, **clarification
needed**, and **missing input**. Set expected amounts and source rows locally
before running a model. Keep portfolio values, trade IDs, expected answers,
and model replies under `private/`. This document defines the benchmark
questions and scoring criteria. It does not report a benchmark run.

## First local evaluation

Qwen3-8B with the existing supervised evidence adapter scored **27/40** over
20 locally generated responses. The model received a question-specific
evidence packet, so this measured answer synthesis rather than record
retrieval. A reviewer checked numerical claims against the holdings snapshot
and applied the rubric above.

| Section | Score |
| --- | ---: |
| Portfolio and risk | 11/18 |
| Positions and trades | 12/18 |
| Tax reporting | 4/4 |
| **Total** | **27/40** |

Both tax answers earned credit for identifying unavailable source evidence.
The run did not verify any tax amount. The main zero-credit failures were
using position marks or gains to infer assignment obligations, assuming
unconfirmed spread legs and deliverables, and confusing a close month with
the option expiration. The question evidence, replies, scoring notes, and
holdings annex remain local.
