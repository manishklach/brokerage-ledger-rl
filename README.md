# Brokerage Ledger RL

Local-first Schwab transaction reconciliation and reward verification. The Runpod
target is Qwen3.8-27B, with Qwen3-8B planned for the first supervised and
verifiable-reward training run.

## Run the local audit

Python 3.11+, standard library only.

```powershell
python ledger.py "<path to Schwab CSV>" --output private/audit.json
python -m unittest -v
```

The audit sums Schwab's reported Amount field with decimal arithmetic. Fees are
retained on transactions and are never subtracted a second time by the cash
report. Blank amounts remain missing and their source lines are reported. Net
transaction cash is a cash-flow figure. Realized P&L requires matched opening
lots and basis. The report uses posted dates for its date range and effective
dates to propose spread candidates.

A vertical candidate has opposite sides in the same open/close phase, same
effective date, underlying, expiry, option right and absolute quantity, and
different strikes. The code proposes only mutually unique pairs. A unique pair
still requires independent confirmation because these fields do not establish
order membership. Competing matches remain ambiguous.

The initial reward requires exact confirmed source lines and exact net cash.
Only independently verified or synthetic labels should be used as reward
targets. Realized P&L, strategy attribution, rolls, and wash-sale lot matching
require additional implementation and source evidence. Keep raw and derived
brokerage data local. The private/ and artifacts/ folders are ignored by Git.

## Synthetic GPU pilot

On a CUDA-enabled Linux PyTorch environment, install the pinned dependencies and
run the pilot. This script generates its own inputs from synthetic data.

```bash
python -m pip install -r requirements-pilot.txt
python -u train_pilot.py --output artifacts/pilot
```

The same held-out synthetic cases score the stock, SFT, and GRPO models.
The scorecard and each adapter are saved in the output directory. This pilot
tests spread-leg identification and cash arithmetic. It uses a single
synthetic case family, so its scores cannot establish real-account accuracy.

## Provisional option lot matching

```powershell
python option_lots.py "<path to expanded Schwab CSV>" --month 2026-10 --output private/october-option-lots.json
```

Provide one continuous export per account. Every fully covered close includes
the opening source rows, matched quantities, allocated cash and provisional
realized P&L. Earlier closes consume inventory before the report month.
The estimate assumes FIFO starting with zero known inventory and uses reverse
CSV row order for ties in effective dates. Broker lot elections and pre-export
positions can change the result. Compare against Schwab's realized gain/loss
detail before using matches as evaluation labels. Assignment, exercise,
expiration, splits, and cancellations require separate review.
