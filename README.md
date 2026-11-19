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

## Reconcile against Schwab exports

```powershell
python reconcile.py "<transactions CSV>" "<realized gain/loss CSV>" "<holdings CSV>" --month 2026-10 --as-of 2026-11-19 --output private/schwab-reconciliation.json
```

The realized comparison groups option contracts by effective close date and
checks quantity, opening-date allocation, and reported gain/loss. Group ties
do not establish individual lot identity when several fills share a date.
The holdings comparison checks signed option quantities across the entire
export window, starting from zero. It requires aligned account scope,
snapshot date, and opening inventory for a full reconciliation.

## Local held-out lot evaluation

```powershell
python lot_eval.py "<transactions CSV>" private/schwab-reconciliation.json --month 2026-10 --output private/october-lot-eval.json
```

The report includes broker-checked single-close, single-lot cases. Keep all
inputs and labels under private/. The cases were selected from FIFO ties
and measure performance on that subset. The separate diagnostic compares
FIFO and LIFO against all broker groups the reconciliation joined.

Use --predictions with a local JSON object keyed by case ID. Each prediction
has a quantity_by_open_date object keyed by ISO dates and a pnl decimal
string. Evaluation scores allocation, P&L, and their joint exact match.

## Lot-evidence post-training

```bash
python -u train_pilot.py --task lot --sft-steps 32 --rl-steps 24 --eval-count 48 --output artifacts/lot-pilot
```

The synthetic task supplies the requested opening date, action, and quantity.
The model either returns the supporting row IDs or flags insufficient evidence.
The reward checks both the status and the exact row IDs. Replies are saved for
all three checkpoints so over-abstention can be detected.

Build the private October prompts with private_lot_cases.py using the original
transactions and reconciliation. Run evaluate_private_model.py with a local
Qwen3-8B checkpoint and the SFT and RL adapter folders. The runner uses local
checkpoint files and reports exact matches separately for supported and missing
cases. This task checks documented opening evidence. P&L and remaining
inventory are scored separately by the lot reconciliation workflow.
