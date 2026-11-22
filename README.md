# Brokerage Ledger RL

A local-first toolkit for brokerage portfolio and options analysis. A deterministic
ledger reconciles broker-reported lots, calculates portfolio figures, and cites
source rows. The language model routes questions and identifies missing evidence.
The workflow is read-only.

The project is licensed under [Apache 2.0](LICENSE).

## What’s available in v0.2.0

- Run the ledger locally to reconcile option lots, check a holdings snapshot,
  and generate a portfolio report with source row references. The
  analysis API accepts normalized broker records.
- Load the report into the private query workspace. Ten examples work
  immediately with the sample portfolio or your own report. Results display
  readable values, missing inputs, and expandable evidence.
- Free-form questions need an Inkling 2 Mini endpoint. The model selects
  one of the supported report queries. The report stays in the browser.
  The managed connection is pending live endpoint setup.
- Stock Inkling scored 45/48 on the expanded synthetic evidence holdout.
  All three truncated cases passed when retried at a higher token cap.
  A pinned vLLM configuration also passed one synthetic query on H100.

[Get started with a portfolio report](#generate-a-report-for-the-query-ui) ·
[Read the project write-up](BLOG.md) ·
[Download v0.2.0](https://github.com/manishklach/brokerage-ledger-rl/releases/tag/v0.2.0)

## Current model direction

**Inkling 2 Mini is the current model for evaluation.** The
[expanded evidence holdout](#expanded-inkling-holdout) and targeted retry
support deferring fine-tuning while we improve query handling and collect
unseen broker-backed cases. Prior GPU experiments used different output budgets
and are regression results under their recorded settings.
See the [GPU benchmark](#inkling-2-mini-gpu-baseline).
Brokerage CSVs and account-level outputs stay in the local Git-ignored
`private/` directory.

## What we trained with Qwen

We post-trained Qwen3-8B on a Runpod NVIDIA RTX 4090 using custom synthetic
brokerage examples. Supervised fine-tuning (SFT) trained a LoRA adapter.
Follow-up Group Relative Policy Optimization (GRPO) runs tested executable
rewards. The early runs used synthetic data only. A later SFT run used
redacted examples derived from the 2025 Schwab reconciliation. The raw
exports stayed local.

The checkpoint is a specialized Qwen3-8B variant made from the original base
model and its matching LoRA adapter. SFT and GRPO are both forms of
post-training. The benchmark results do not establish state-of-the-art
performance.

| Evaluation | Result | Scope |
| --- | --- | --- |
| October opening evidence | Stock 32/53, supervised 53/53 | Exact status and supporting row IDs |
| Redacted 2025 broker-link holdout | Stock 0/54, previous SFT 11/54, new SFT 54/54 | Exact status and aliases on held-out contracts with the same prompt format |
| Harder private holdout | Supervised 140/196 | Opening evidence across additional months |
| Ledger-controlled close routing | Stock and supervised both 26/30 | Filter extraction over a 196-case local index |
| Portfolio, position, and tax questions | Supervised 27/40 rubric points | Answer synthesis from prepared evidence. Tax amounts were unavailable. |

SFT produced the clearest gains. RL sometimes improved detection of missing
evidence but made the model reject more supported cases. This is a small
version of Applied Compute's workflow of adapting a base model and measuring
it on a domain task. AC2 also manages enterprise serving and ongoing model
improvement. [Applied Compute's AC2 overview](https://www.appliedcompute.com/platform/introducing-ac2)

## What the project does

1. Normalize one account's transaction export, keeping source row
   numbers, posted dates, effective dates, quantities, reported amounts, and
   fees.
2. Audit transaction cash and propose vertical spread pairings for review.
3. Reconstruct provisional option lots, then compare opening-date allocations,
   quantities, and realized P&L with broker-reported closed-lot detail. Compare signed
   position quantities with a separate holdings snapshot.
4. Post-train Qwen3-8B on synthetic cases using supervised fine-tuning (SFT) and
   Group Relative Policy Optimization (GRPO). A Python verifier scores exact
   source row IDs and, depending on the task, cash or evidence status.
5. Evaluate checkpoints on the same held-out inputs. Synthetic evaluation can
   run on a GPU Pod. Broker-derived prompts and labels stay local.

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
This command reproduces the historical Qwen training pilot.

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

Put brokerage exports in the Git-ignored `private/inputs/` directory.
Keep derived reports and private prompts under `private/`, and model
checkpoints under `artifacts/`. Check new commits for sensitive files
before pushing. Runpod examples are synthetic or deliberately redacted.
Raw exports stay local.

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

### Enforce evidence in the ledger

Replay saved model replies against the deterministic evidence gate:

```powershell
python ledger_evidence.py private/hard-lot-holdout.json private/hard-lot-sft-scorecard.json --output private/hard-lot-ledger-replay.json
```

The gate returns exact required and recorded quantities, shortfalls, and
matching transaction rows by date. The supervised model scored 140/196
while the gate reproduced 196/196 holdout labels and reduced false claims
of support from 43 to zero in this replay. The holdout labels use the same
evidence rule, making this a consistency check rather than independent
validation of remaining inventory, realized P&L, or natural-language
interpretation. The replay uses previously saved model replies.

### Natural-language ledger routing

The routing benchmark generates 30 questions from the private harder holdout.
Each prompt supplies a candidate list of closes and asks the model to route
to an evidence check, ask for clarification, or report no match. A close ID
must refer to a listed candidate. The ledger retrieves the recorded claim
and computes evidence status and source rows from structured inputs.

```powershell
python query_benchmark.py private/hard-lot-holdout.json --output private/query-benchmark.json
python evaluate_gguf.py private/query-benchmark.json --model artifacts/qwen3-8b-base/qwen3-8b-q4_0.gguf --tokenizer artifacts/qwen3-8b-base --sft artifacts/lot-pilot/sft/adapter.gguf --query-cases --output private/query-model-scorecard.json
```

The benchmark scores schema-valid output, operation, and close ID
separately. Candidate retrieval and unrestricted natural-language
questions are outside this benchmark.

On the first local 30-question run, stock Qwen routed 17/30 correctly and
the supervised adapter routed 18/30. On the 18 questions with a unique
match, the ledger returned the expected evidence for all 17 correct stock
routes and all 18 supervised routes. Both models attempted an evidence
check for all eight ambiguous and four no-match questions. All replies
matched the JSON schema. Private prompts and replies are Git-ignored.

### Ledger-controlled close resolution

The filter benchmark reruns the same questions without candidate lists.
Qwen extracts the ticker, expiration, strike, right, close month, and
source line. The ledger matches those filters against the local evidence
index and runs the evidence check only for a unique match.

```powershell
python query_benchmark.py private/hard-lot-holdout.json --output private/query-filter-benchmark.json
python evaluate_gguf.py private/query-filter-benchmark.json --model artifacts/qwen3-8b-base/qwen3-8b-q4_0.gguf --tokenizer artifacts/qwen3-8b-base --sft artifacts/lot-pilot/sft/adapter.gguf --filter-index private/hard-lot-holdout.json --output private/query-filter-scorecard.json
```

Both models routed 26/30 correctly: 14/18 unique closes, 8/8
clarifications, and 4/4 no-match cases. Stock extracted all filters
exactly on 22/30 questions and SFT on 24/30. All 30 gold filter sets
resolved correctly over the 196-case local evidence index. This test
does not establish retrieval accuracy over a full brokerage account.

## Portfolio and position question benchmark

The [TQQQ, SOXL, and XLK benchmark](PORTFOLIO_QUESTION_BENCHMARK.md) defines
20 portfolio risk, position, and tax-reporting questions with input
requirements and scoring criteria. Prepare expected values from local
brokerage data before scoring model answers.

## Packaging

Install the standard-library ledger commands with `python -m pip install .`
on Python 3.11 or newer. The training experiments have separate runtime
requirements. Run the ledger tests with `python -m unittest discover`.

Use a **source ZIP** for the current CLI prototype. The ledger and its tests
run with Python 3.11+ and the standard library. Build the ZIP from a reviewed
Git commit so recipients can reproduce the exact source version.

```powershell
git ls-files
New-Item -ItemType Directory -Force artifacts | Out-Null
git archive --format=zip --prefix=brokerage-ledger-rl/ --output=artifacts/brokerage-ledger-rl-source.zip HEAD
tar -tf artifacts/brokerage-ledger-rl-source.zip
```

Review the archive listing before sharing. Git archives every tracked file
at the selected commit, even if an ignore rule would match it. After
extracting the ZIP, run `python -m unittest -v` and use the local workflow
above with your own exports.

| Component | How to package it |
| --- | --- |
| Base model and tokenizer | Obtain Qwen3-8B from its publisher and record the revision or checksums. For CPU inference, use a compatible GGUF and local tokenizer files. |
| Supervised LoRA | Distribute the matching adapter and its configuration separately. For llama.cpp, provide the converted adapter GGUF and record its conversion settings and checksum. |
| Local inference | Use a Python environment with Transformers and a compatible llama-cpp-python build. The CPU benchmark used llama-cpp-python 0.3.35. |
| GPU training | Use the source ZIP with `requirements-pilot.txt` in a CUDA-enabled PyTorch environment. The pilot generates its own synthetic examples. |
| Brokerage data | Each user supplies local exports. Keep exports, derived reports, private prompts, model replies, and credentials outside distributed bundles. |

A source ZIP plus a separate adapter is the simplest handoff. A Python
wheel or desktop installer would require additional packaging work. Include
the source commit, base model revision, adapter checksum, and tested
runtime versions with a release.

## Annual broker review

With both CSVs for the same account, generate the local annual report:

```powershell
python period_review.py "private/inputs/2025 Transactions.csv" "private/inputs/2025 Realized.csv" --year 2025 --output private/2025-period-review.json
```

The report includes monthly transaction cash, option-close comparisons,
and broker-reported short-term and long-term realized amounts by
underlying. It keeps source row numbers, flags lots opened before the
transaction export, and compares proceeds less basis with the reported
gain and disallowed loss. It reports Schwab's fields as provided. It
does not infer replacement lots or resolve close-date mismatches.

The realized export is the source of each broker lot's reported open/close
allocation. The annual review joins its Transaction Closed Date to
transaction events and checks quantity at the instrument-and-date level.
It preserves the displayed Closed Date alongside the transaction date.
Opening records are linked by the broker's opening date where available,
with side and quantity checks and explicit statuses for gaps. A group
match corroborates the available source rows. It does not assign individual
fills within a many-to-many group or reconstruct inventory before the export.

### 2025 broker-link supervised fine-tune

Generate redacted examples locally, then pass the explicit split to the GPU
pilot. The generator keeps each instrument in one split and omits the
original ticker, dates, dollar amounts, and source IDs. Each prompt gives
reconciled evidence descriptions and asks for a status and temporary
source aliases.

```powershell
python broker_training_examples.py private/2025-period-review.json --output private/broker-sft-redacted.json
python train_pilot.py --task lot --examples-file private/broker-sft-redacted.json --sft-steps 160 --rl-steps 0 --output artifacts/broker-sft
```

Training used 270 examples. The 54 held-out examples use the same prompt
format and test whether the model can cite provided evidence labels.
The result does not measure retrieval from raw brokerage records or
accuracy on new question formats.

## Generate a report for the query UI

1. Export **Transaction History**, **Realized Gain/Loss Detail**, and a dated
   **Positions** snapshot from Schwab for the same account. Save them locally
   as `private/transactions.csv`, `private/realized.csv`, and
   `private/holdings.csv`. Transaction history can cover earlier periods to
   help link opening trades.
2. From the repo root, run this with Python 3.11 or later. Replace the month
   with the realized period you want and the date with the date on your
   holdings export.

   ```powershell
   python portfolio_review.py private/transactions.csv private/realized.csv private/holdings.csv --month 2025-12 --as-of 2025-12-31 --output private/portfolio-report.json
   ```

3. In the query workspace, select **Load portfolio report** and open
   `private/portfolio-report.json`. Pick one of the ten examples and select
   **Run query**. The workspace displays the computed answer as readable
   text with expandable source evidence.
4. For free-form questions, select **Inkling connection** and enter the HTTPS
   base URL ending in `/v1` for a running OpenAI-compatible Inkling 2 Mini
   server. Use an API key if the server requires one. The server must allow
   requests from the site's origin. Inkling routes the question to a
   supported report query while the JSON stays in the browser.

The JSON comes from the CSVs and can be regenerated whenever they change.
Generating the report requires no model training. The hosted workspace is
private. The command above works independently of access to the workspace.

## Monthly portfolio review

Monthly transaction counts and cash use the posted month. Option close
comparisons instead use the transaction's effective date and the broker's
Transaction Closed Date when supplied, falling back to Closed Date. Annual
broker-reported totals still use Closed Date. A close at a month boundary
can therefore appear under different months in these views.

The standalone `option_lots.py` CLI uses the effective month by default.
Use `--date-basis posted` to reproduce the previous posted-month view.

Unsupported option events affect provisional closes from their effective
date forward. The matcher scopes a blocker to the long or short inventory
when the action identifies the affected side. A signed expiration,
assignment, or exercise can remove all known remaining lots on a side
when its quantity ties and that side has no prior blockers. Partial
settlements or earlier uncertainty still require review. The holdings
reconciliation reports unresolved contracts with source lines and reasons.

Run the local workflow from the transaction, realized gain/loss, and dated
positions exports. The optional evidence index supports the benchmark's
September close question.

```powershell
python portfolio_review.py "private/inputs/2025 Transactions.csv" "private/inputs/2025 Realized.csv" private/inputs/holdings-2026-11-19.csv --month 2025-12 --as-of 2026-11-19 --evidence-index private/hard-lot-holdout.json --output private/december-2025-portfolio-review.json
```

The report keeps the realized reporting month and holdings snapshot date
explicit. It calculates broker-reported realized results by underlying and
term, marks-based concentration and option expirations, and points to source
CSV rows. Reported market values and gross marks measure the stated marks.
Directional delta exposure and stress repricing require separate inputs.

The first run covered 198 December transactions and 79 realized lots, of
which 75 linked to closing transaction groups by date and quantity. The
scripted workflow scored 33/40 on the documented 20 questions. It answered
seven, returned partial evidence on seven, requested clarification on three,
and flagged missing inputs on three. The tax answers were checked against
the supplied 2025 realized CSV. This run used numbered queries and automatic
record lookup. The earlier 27/40 run tested a model answering from prepared
evidence and measures a different part of the system.

### Portfolio routing GPU pilot

The portfolio router maps a natural-language question to one of the 20
documented ledger queries, or returns clarification or unsupported. The
synthetic exercise measures intent classification. It does not extract
arbitrary query parameters or execute ledger queries.

```bash
python train_pilot.py --task portfolio-route --train-count 264 --eval-count 44 --sft-steps 160 --rl-steps 0 --output artifacts/portfolio-route
```

The run used an RTX 4090 and 264 examples based on synthetic wording
templates. The test used 44 separately worded questions, two per route,
with the same route catalog supplied to each checkpoint. Stock Qwen3-8B,
the prior broker-evidence adapter, and the new routing adapter each
scored **38/44** exact. The new adapter fixed some individual routes
but introduced others. All three confused at least one exposure ranking,
bid/ask, and roll question. No brokerage records were uploaded for
this run.

### Inkling 2 Mini GPU baseline

The same 44 synthetic routing questions also ran through stock
[Inkling 2 Mini](https://thinkingmachines.ai/model-card/inkling-2-mini/) on
a single Runpod B200 using the [vLLM model image](https://recipes.vllm.ai/thinkingmachines/Inkling-2-Mini).

| Checkpoint and decoding | Exact routes | Length-truncated |
| --- | ---: | ---: |
| Qwen3-8B stock and both tested adapters, 80 tokens | 38/44 each | See the Qwen pilot scorecards |
| Inkling 2 Mini, default effort and 80 tokens | 4/44 | 40/44 |
| Inkling 2 Mini, low effort and 512 tokens | 41/44 | 0/44 |

The rows use the same prompts and scorer. The token budgets and reasoning
settings differ, so the higher score does not establish an equal-budget
advantage. The low-effort run missed one expiration-window, one fund-overlap,
and one partial-close question. This experiment used stock Inkling weights
and did not include fine-tuning or any brokerage inputs.

With an authenticated OpenAI-compatible vLLM server running, set
PORTFOLIO_BENCHMARK_API_KEY in the environment. The client also needs curl
on PATH.

```bash
python evaluate_portfolio_server.py --base-url https://YOUR_SERVER/v1 --model thinkingmachines/Inkling-2-Mini --reasoning-effort low --max-tokens 512 --startup-timeout 1200 --output artifacts/inkling-2-mini/portfolio-route-low-effort.json
```

### Inkling fine-tuning direction

Use Inkling 2 Mini as the base for the next portfolio-routing SFT run.
Keep stock Inkling as the primary baseline and retain Qwen scores for
historical comparison. Use the same decoding settings for stock and
fine-tuned Inkling and report exact routes, missed routes, and cutoffs.
The existing 44 questions are a regression set. Add a fresh holdout before
making a generalization claim.

Prepare the synthetic training and evaluation splits as chat JSONL:

```bash
python prepare_inkling_sft.py --output artifacts/inkling-2-mini/sft-data
```

The exporter writes 264 training examples and 44 held-out questions
without reading brokerage files. Keep the evaluation split out of model
updates. NVIDIA's published NeMo AutoModel recipes use four GB200s, while
SkyRL documents a Mini training configuration on eight B200s. The single
B200 setup above is verified for inference. [NeMo AutoModel recipe](https://docs.nvidia.com/nemo/automodel/nightly/model-coverage/vision-language-models/thinkingmachines/Inkling-2-Mini) · [SkyRL recipe](https://docs.skyrl.ai/docs/models/inkling2)

### Lot evidence evaluation

Use the report's redacted lot examples to evaluate whether Inkling returns the
expected evidence status and cites exactly the expected row aliases. The
evaluator adds 24 synthetic unverified-close cases and reports exact accuracy
for each status. Keep the real exports and scorecard in the ignored
`private/` folder.

```bash
python broker_training_examples.py private/2024-period-review.json --output private/inkling-2024-lot-evidence.json
python evaluate_portfolio_server.py --base-url https://YOUR_SERVER/v1 --model thinkingmachines/Inkling-2-Mini --reasoning-effort low --max-tokens 512 --lot-holdout private/inkling-2024-lot-evidence.json --output private/inkling-2024-stock-h100.json
```

The prompts describe already-classified ledger evidence. This benchmark
measures interpretation and citation accuracy for that evidence.

### Fresh opening-evidence checks

The six independently labeled synthetic cases cover cross-month partial
allocations, exact multi-row allocations, insufficient quantity, and
ambiguous lot elections. Keep these cases out of training. They are a
targeted regression check with a small sample size.

```bash
python evaluate_portfolio_server.py --base-url https://YOUR_SERVER/v1 --model thinkingmachines/Inkling-2-Mini --reasoning-effort low --max-tokens 512 --fresh-evidence --output private/inkling-fresh-evidence.json
```

The scorecard records exact matches by status, failed requests, truncation,
and latency for completed requests.

### Expanded Inkling holdout

The expanded set has 48 synthetic contracts across eight month boundaries,
with 16 cases each for supported, ambiguous, and missing evidence. It
includes exact split fills, competing allocations, one-contract shortfalls,
and distractors with a different strike, action, or date. The answer keys
are checked against the quantity verifier. Keep this set out of training
and prompt selection. The six earlier cases remain available as a regression
set using `--fresh-evidence`.

```bash
python evaluate_portfolio_server.py --base-url https://YOUR_SERVER/v1 --model thinkingmachines/Inkling-2-Mini --reasoning-effort low --max-tokens 512 --expanded-evidence --output private/inkling-expanded-evidence.json
```

The report adds exact scores by scenario, status-only accuracy, and false
claims of support. The cases test opening evidence rules on synthetic data.
A separate broker-backed holdout requires contracts that were kept out of the
earlier experiments.

Stock Inkling 2 Mini on a Runpod B200 scored **45/48** exact at low reasoning
effort with a 512-token cap. It made zero false claims of support across the
32 ambiguous or missing-evidence cases. All three misses were truncated.
Those three cases scored **3/3** when retried at 1,024 tokens with the same
reasoning setting. The retry covered only the truncated cases.

Estimated GPU charges were $1.20 for the first startup attempt, $1.95 for the
completed baseline, and $0.60 for the targeted retry. The temporary Pods
were removed after use. Fine-tuning was deferred.

### H100 vLLM smoke test

A single Runpod H100 SXM served stock Inkling 2 Mini and returned the correct
status and citations on one synthetic case. The release-day image failed
at an Inkling CUDA kernel on our H100. The older generic nightly used as the
base below needed the Mini model registration and an updated Transformers
dependency. The combination below passed a live request. Full H100
benchmark coverage remains unmeasured.

Use CUDA 13.2 or later on the host. The tested Linux amd64 base image was
`vllm/vllm-openai@sha256:3dfcb2ba18f41fce7400d643e52210a6c4f198019ead77146e9fb649ee600ceb`.
Override the container entrypoint to run Bash and use this startup command.
Set `VLLM_API_KEY` in the runtime environment and expose port 8000 for a
temporary test.

```bash
uv pip install --system --no-deps \
  'https://wheels.vllm.ai/ab18334a4f60da74db7de89fe95594e5ed0cda36/vllm-0.34.0rc1.dev1125%2Bgab18334a4-cp38-abi3-manylinux_2_28_x86_64.whl' \
  'transformers==5.24.0' &&
exec vllm serve thinkingmachines/Inkling-2-Mini \
  --host 0.0.0.0 --port 8000 --reasoning-parser inkling \
  --max-model-len 4096 --max-num-seqs 2 --enforce-eager
```

## Broker integrations

Schwab is the first supported CSV integration.

The portfolio engine accepts normalized transactions, realized lots, and positions
through `portfolio_review.build_portfolio_report`. An integration translates a
broker's export to those records and preserves source row numbers. The Schwab
readers are the working example. The existing CSV command-line tools currently
load Schwab formats. Other brokers can use the Python API by supplying their own
readers.

| Input | Normalized contract | Schwab example |
| --- | --- | --- |
| Transactions | A nonempty list of `ledger.Transaction` records with Python dates, canonical actions, source lines, and `Decimal` values for numeric fields | `ledger.read_export` |
| Realized lots | Mappings with `broker_source_line`, `instrument`, `underlying`, `is_option`, positive `quantity`, ISO dates `opened`, `closed`, `transaction_closed`, `term`, `wash_sale_flag`, and the `portfolio_review.AMOUNTS` decimal fields | `period_review.read_schwab_realized` |
| Positions | Mappings with `source_line`, `symbol`, `underlying`, `kind`, `is_option`, and nullable decimal fields `quantity`, `market_value`, `unrealized` | `portfolio_review.read_holdings` |

Use `ROOT YYYY-MM-DD STRIKE C/P` consistently for option instruments and
`ledger.OPTION_ACTIONS` for option opens and closes. Map asset kinds to the
values used in `holdings_review` and keep each snapshot's date with its source.
Validate the new broker's date, quantity, cash, and lot conventions against its
own reports. Existing broker-derived evaluations are scoped to Schwab.

### Schwab export coverage

We have tested Schwab transaction history, realized gain/loss detail, and
position snapshot CSV layouts. New data in the same layouts can be imported.
Other Schwab layouts may need parser work for alternate headers, title or
subtotal rows, missing fields, or account identifiers. Test each new format
with redacted or synthetic fixtures and reconcile row counts and signed
amounts before relying on it.

Import new trades as ledger data. Once an export maps to the same ledger
fields, its layout does not require retraining. Consider more SFT when a
repeatable interpretation error survives fixes to the parser, ledger, or
prompt. One candidate is confusing a close month with an option expiration.
Turn the error into labeled question-to-filter examples and compare stock,
the existing adapter, and the new adapter on a fresh holdout. Keep contracts
or time periods separate between training and evaluation. Make a separate
data-handling decision before using any real brokerage rows for cloud training.

### Schwab example inputs

| Schwab export | Fields used | Purpose |
| --- | --- | --- |
| Transaction history | Date, Action, Symbol, Description, Quantity, Price, Fees & Comm, Amount | Source transactions and reported cash |
| Realized Gain/Loss detail | Symbol, Closed Date, Opened Date, Quantity, Gain/Loss, wash-sale flag | Independent broker lot and P&L comparison |
| Positions snapshot | Symbol, signed quantity, snapshot date supplied via CLI | Open options quantity comparison |

Use one continuous transaction export per account and align the scope and
dates of the other exports. If a newer export contains all rows in an earlier
one, use the newer file on its own.
