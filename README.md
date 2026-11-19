# Brokerage Ledger RL

A local-first research project for reconciling Schwab options activity and
post-training an open-weight model with verifiable rewards. A deterministic
ledger handles quantities and cash. The model learns to identify supporting
transaction rows and flag missing evidence. The project analyzes past trades.

## What the project does

1. Normalize one account's Schwab transaction export, keeping source row
   numbers, posted dates, effective dates, quantities, reported amounts, and
   fees.
2. Audit transaction cash and propose vertical spread pairings for review.
3. Reconstruct provisional option lots, then compare opening-date allocations,
   quantities, and realized P&L with Schwab's closed-lot detail. Compare signed
   position quantities with a separate holdings snapshot.
4. Post-train Qwen3-8B on synthetic cases using supervised fine-tuning (SFT) and
   Group Relative Policy Optimization (GRPO). A Python verifier scores exact
   source row IDs and, depending on the task, cash or evidence status.
5. Evaluate checkpoints on the same held-out inputs. Synthetic evaluation can
   run on a GPU Pod. Broker-derived prompts and labels stay local.

## Inputs

| Schwab export | Fields used | Purpose |
| --- | --- | --- |
| Transaction history | Date, Action, Symbol, Description, Quantity, Price, Fees & Comm, Amount | Source transactions and reported cash |
| Realized Gain/Loss detail | Symbol, Closed Date, Opened Date, Quantity, Gain/Loss, wash-sale flag | Independent broker lot and P&L comparison |
| Positions snapshot | Symbol, signed quantity, snapshot date supplied via CLI | Open options quantity comparison |

Use one continuous transaction export per account and align the scope and
dates of the other exports. If a newer export contains all rows in an earlier
one, use the newer file on its own.

## Run the local workflow

Ledger and report commands use Python 3.11+ and the standard library. Put
exports under the Git-ignored `private/` folder or use absolute paths to the
original files. The example uses October 2026. Adjust the reporting month and
snapshot date to match your inputs.

```powershell
python ledger.py private/transactions.csv --output private/audit.json
python option_lots.py private/transactions.csv --month 2026-10 --output private/october-option-lots.json
python reconcile.py private/transactions.csv private/realized.csv private/holdings.csv --month 2026-10 --as-of 2026-11-19 --output private/schwab-reconciliation.json
python lot_eval.py private/transactions.csv private/schwab-reconciliation.json --month 2026-10 --output private/october-lot-eval.json
python private_lot_cases.py private/transactions.csv private/schwab-reconciliation.json --month 2026-10 --output private/october-evidence-cases.json
python -m unittest -v
```

The cash audit sums Schwab's reported Amount using decimal arithmetic. Blank
amounts remain missing and are flagged by source row. Fees are preserved and
the audit avoids deducting fees a second time. Net transaction cash and
realized P&L are separate measures.

The spread audit proposes mutually unique opposite-side pairs with the same
effective date, open or close phase, underlying, option right, expiry, and
absolute quantity, and different strikes. A unique pairing still needs
trade-confirmation evidence to establish order membership.

The lot matcher consumes earlier closes, handles partial fills across lots,
and allocates cash to cents. It uses FIFO with zero starting inventory and
reverse CSV row order for same-day ties. The diagnostic also compares LIFO.
Missing pre-export inventory, broker lot elections, same-day ordering, and
contract events can affect the result. The matcher flags unsupported events.
Comprehensive wash-sale matching, assignments, exercise accounting, strategy
attribution, and roll reconstruction remain research work.

## Post-train on synthetic data

Run these commands on a CUDA-enabled Linux PyTorch environment. The training
script generates synthetic inputs itself. Qwen3-8B ran with 4-bit NF4 and LoRA
on a single RTX 4090 Runpod Pod.

```bash
python -m pip install -r requirements-pilot.txt
python -u train_pilot.py --task spread --output artifacts/spread-pilot
python -u train_pilot.py --task lot --sft-steps 32 --rl-steps 24 --eval-count 48 --output artifacts/lot-pilot
```

- **Spread task:** Return the exact row IDs of both legs and their signed net
  cash. The verifier checks both fields.
- **Lot-evidence task:** Given a requested opening date, quantity, and action,
  return the supporting row IDs or flag insufficient evidence. This checks
  whether the recorded rows support the request. The ledger separately handles
  remaining inventory and P&L.

Each run saves a stock, SFT, and GRPO scorecard, individual replies, and both
LoRA adapters. These were the results on the synthetic lot-evidence pilot:

| Checkpoint | Supported cases | Missing evidence | Total |
| --- | ---: | ---: | ---: |
| Stock Qwen3-8B | 0/24 | 19/24 | 19/48 |
| Supervised fine-tuning | 20/24 | 17/24 | 37/48 |
| GRPO | 7/24 | 24/24 | 31/48 |

Supervised tuning led this pilot overall. GRPO detected more missing evidence
but rejected more supported cases. These results measure the synthetic task.
The project keeps Qwen3.8-27B as a possible scale-up after private validation.

## Evaluate locally against broker evidence

Acquire the Qwen3-8B model files and the matching SFT adapter before running
the evaluator. Install PyTorch, Transformers, Accelerate, PEFT and
bitsandbytes with support for your local CUDA or CPU backend. The evaluator
loads the base and adapters from local paths. The GRPO adapter is optional.

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
python evaluate_private_model.py private/october-evidence-cases.json --model artifacts/qwen3-8b-base --sft artifacts/lot-pilot/sft --output private/october-model-scorecard.json
```

The evidence scorecard breaks out supported and missing-evidence cases.
Clean examples are selected from broker ties, so use them as regression cases
and inspect the disagreement set alongside them. For the separate allocation
and P&L benchmark, `lot_eval.py --predictions` accepts a JSON object keyed by
case ID. Each prediction has a `quantity_by_open_date` object keyed by ISO
dates and a `pnl` decimal string.

## Source map

| File | Role |
| --- | --- |
| `ledger.py` | CSV parsing, cash audit, and vertical spread candidates |
| `option_lots.py` | Provisional option lot consumption and P&L |
| `reconcile.py` | Closed-lot and holdings comparisons |
| `lot_eval.py` | Broker-checked allocation and P&L evaluation |
| `private_lot_cases.py` | Local opening-evidence prompts and labels |
| `pilot_data.py`, `lot_pilot_data.py`, `rewards.py` | Synthetic cases and executable checks |
| `train_pilot.py`, `evaluate_private_model.py` | GPU pilot and local checkpoint comparison |

## Data handling

Keep raw brokerage files, derived reports, private prompts, weights, and
credentials out of Git. The repository ignores `private/`, `artifacts/`,
CSV and JSONL exports, and adapter weights. Upload only the training code and
synthetic cases to Runpod. Repository visibility is an additional control.

### October holdout result

Both checkpoints ran locally with the same Qwen3-8B Q4_0 GGUF base,
llama.cpp runtime, prompt format, and greedy decoding. The supervised
checkpoint used the converted LoRA adapter. Exact match required both the
expected evidence status and the exact supporting source row IDs.

| Checkpoint | Supported | Missing evidence | Total |
| --- | ---: | ---: | ---: |
| Stock Qwen3-8B | 0/21 | 32/32 | 32/53 |
| Supervised LoRA | 21/21 | 32/32 | 53/53 |

The result covers this selected October evidence benchmark. A new holdout
should include other months, ambiguous lots, and partial quantities before
using the score to justify a larger model. P&L accuracy and broker lot
allocation require their own evaluations.

To reproduce the CPU comparison, prepare a Qwen3-8B Q4_0 GGUF, its local
Hugging Face tokenizer files, and a compatible LoRA GGUF converted from the
SFT checkpoint. The run used llama-cpp-python 0.3.35.

```powershell
python evaluate_gguf.py private/october-evidence-cases.json --model artifacts/qwen3-8b-base/qwen3-8b-q4_0.gguf --tokenizer artifacts/qwen3-8b-base --sft artifacts/lot-pilot/sft/adapter.gguf --output private/october-gguf-scorecard.json
```

### Harder lot-evidence benchmark

Build a fresh local holdout from months outside October. The builder excludes
contract identities seen in the October reconciliation. Broker-reported dates
and quantities form the claims to check against recorded opening rows.

```powershell
python hard_lot_holdout.py private/transactions.csv private/realized.csv --months 2026-07 2026-08 2026-09 2026-11 --output private/hard-lot-holdout.json
```

Cases distinguish supported evidence, missing quantities or dates, and
ambiguous row allocations. A case can include multiple opening dates or an
opening row larger than the matched quantity. The evidence rule checks the
recorded rows. Prior consumption and broker lot elections need a separate
inventory and accounting check.

The matching GPU curriculum generates synthetic cases on demand. Compare the
stock, previous SFT (optional), new SFT, and GRPO scorecards by evidence status.
The hard-lot GRPO reward gives +1 for exact status and rows, -0.5 for claiming
support when evidence is missing, and 0 for other errors. The evaluation metric
remains exact match for every checkpoint.

```bash
python -u train_pilot.py --task hard-lot --train-count 240 --sft-steps 64 --rl-steps 36 --eval-count 60 --output artifacts/hard-lot-pilot
```

The existing supervised adapter scored 140/196 exact on the harder private
holdout (58/64 supported, 80/130 missing evidence, and 2/2 ambiguous). It
incorrectly marked 43 missing-evidence cases as supported. The ambiguity
sample is too small for a general performance claim. Run the GGUF evaluator
with --sft-only to reproduce the supervised-only comparison.

The first hard-lot GPU pilot used a balanced, 60-case synthetic holdout
with 20 cases per evidence status:

| Checkpoint | Supported | Missing evidence | Ambiguous | Total | Missing labeled supported |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stock | 0/20 | 3/20 | 18/20 | 21/60 | 1 |
| Previous SFT | 1/20 | 4/20 | 14/20 | 19/60 | 3 |
| New SFT | 3/20 | 7/20 | 16/20 | 26/60 | 6 |
| New SFT + GRPO | 0/20 | 7/20 | 18/20 | 25/60 | 0 |

GRPO eliminated false claims of support in this synthetic test and lost all
exact supported answers. The older private-holdout score used a different
case distribution. Testing either new adapter on the private holdout would
be required to measure transfer.
