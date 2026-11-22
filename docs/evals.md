# Evaluation protocols

See the [canonical benchmark table](../README.md#benchmarks) for scores, run settings, and limits.

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

### October holdout result

Both checkpoints ran locally with the same Qwen3-8B Q4_0 GGUF base,
llama.cpp runtime, prompt format, and greedy decoding. The supervised
checkpoint used the converted LoRA adapter. Exact match required both the
expected evidence status and the exact supporting source row IDs.

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

Report results by evidence status and count claims of unsupported evidence.

### Enforce evidence in the ledger

Replay saved model replies against the deterministic evidence gate:

```powershell
python ledger_evidence.py private/hard-lot-holdout.json private/hard-lot-sft-scorecard.json --output private/hard-lot-ledger-replay.json
```

The gate returns exact required and recorded quantities, shortfalls, and
matching transaction rows by date. The replay checks consistency with
labels constructed from the same evidence rule.

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

Private prompts and replies are Git-ignored.

### Ledger-controlled close resolution

The filter benchmark reruns the same questions without candidate lists.
Qwen extracts the ticker, expiration, strike, right, close month, and
source line. The ledger matches those filters against the local evidence
index and runs the evidence check only for a unique match.

```powershell
python query_benchmark.py private/hard-lot-holdout.json --output private/query-filter-benchmark.json
python evaluate_gguf.py private/query-filter-benchmark.json --model artifacts/qwen3-8b-base/qwen3-8b-q4_0.gguf --tokenizer artifacts/qwen3-8b-base --sft artifacts/lot-pilot/sft/adapter.gguf --filter-index private/hard-lot-holdout.json --output private/query-filter-scorecard.json
```

The index test does not establish retrieval accuracy over a full account.

## Portfolio and position question benchmark

The [TQQQ, SOXL, and XLK benchmark](../PORTFOLIO_QUESTION_BENCHMARK.md) defines
20 portfolio risk, position, and tax-reporting questions with input
requirements and scoring criteria. Prepare expected values from local
brokerage data before scoring model answers.

### Inkling 2 Mini GPU baseline

The same 44 synthetic routing questions also ran through stock
[Inkling 2 Mini](https://thinkingmachines.ai/model-card/inkling-2-mini/) on
a single Runpod B200 using the [vLLM model image](https://recipes.vllm.ai/thinkingmachines/Inkling-2-Mini).

With an authenticated OpenAI-compatible vLLM server running, set
PORTFOLIO_BENCHMARK_API_KEY in the environment. The client also needs curl
on PATH.

```bash
python evaluate_portfolio_server.py --base-url https://YOUR_SERVER/v1 --model thinkingmachines/Inkling-2-Mini --reasoning-effort low --max-tokens 512 --startup-timeout 1200 --output artifacts/inkling-2-mini/portfolio-route-low-effort.json
```

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

### Freeze a broker-backed test set

`freeze_broker_holdout.py` builds a local opening-evidence test set for
specified months. Supply the realized exports and case indexes used in
prior experiments as exclusions. The builder also excludes contracts in
other realized months in the source export and contracts with settlement
events, since this scorer does not reconstruct settlement-adjusted
inventory. It prints coverage counts and a SHA-256 digest and refuses to
overwrite a frozen file.

```bash
python freeze_broker_holdout.py private/transactions.csv private/realized.csv --months 2026-05 2026-06 --exclude-realized private/prior-realized.csv --exclude-cases private/hard-lot-holdout.json --output private/new-broker-holdout.json
python evaluate_portfolio_server.py --base-url http://127.0.0.1:8000/v1 --model thinkingmachines/Inkling-2-Mini --reasoning-effort low --max-tokens 1024 --broker-evidence private/new-broker-holdout.json --output private/inkling-broker-baseline.json
```

Keep the frozen test cases out of training, prompt selection, and checkpoint
selection. Inspect per-status recall, the false-support rate among
unsupported cases, and failed or truncated requests. The score measures
opening-evidence classification under the documented rule. It does not
measure lot elections, settlement attribution, or live Web UI routing.

`private/inkling-broker-holdout-v1.json` is the existing local **186-case**
file used in the attempted paired-generation run. Its 17 supported and
169 missing-evidence cases differ from the external review's 29-case set.
The original 29-case file and scorecard are unavailable here. Use a new
output filename for newly frozen cases so the existing benchmark stays
untouched.


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
