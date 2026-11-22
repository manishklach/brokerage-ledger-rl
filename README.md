# Brokerage Ledger RL

A local-first brokerage ledger that reconciles option lots, calculates portfolio
figures, and reports the rows behind its answers. The browser computes figures
from a local report. Hosted Inkling 2 Mini interprets free-form questions and
returns a structured query plan.

[Release v0.4.0](https://github.com/manishklach/brokerage-ledger-rl/releases/tag/v0.4.0) · [Blog Part 1](BLOG.md) · [Blog Part 2](BLOG_PART_2.md) · [Apache 2.0](LICENSE)

## Current status

- The ledger supports FIFO partial settlements, quarantines unresolved events,
  and defaults to effective dates across monthly and annual reports.
- The private Site serves stock Inkling 2 Mini on an on-demand L4. It handles
  ticker-level realized P&L, snapshot unrealized P&L, and recorded dividends.
- The Inkling attention LoRA pilot ran on one RTX PRO 6000 Blackwell. Step 12
  was selected on synthetic teacher-forced NLL. The paired generation
  comparison on broker evidence remains unfinished.

## Benchmarks

Dates are local run or scorecard dates. When only a commit establishes the
date, the column says **recorded**. An unrecorded decoding parameter is shown
as **unlogged**. Synthetic cases and selected broker cases measure different
tasks. Private source rows and raw scorecards stay local.

| Benchmark | Model or workflow | N and split | Date or run | Decoding and hardware | Metric | Result | Caveat |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Inkling lot-evidence validation | Stock and LoRA steps 4, 8, 12 | 100 synthetic validation cases, 2,252 answer tokens per variant | 2026-11-22 | Teacher-forced, same NeMo runtime and RTX PRO 6000 | Mean NLL per answer token ↓ | Stock **1.1473**, step 4 **0.2941**, step 8 **0.1801**, step 12 **0.1638** | Step 12 was selected solely on this metric. Lower NLL after SFT is expected. Generated accuracy, status recall, and false support are unmeasured. |
| Portfolio intent routing | Stock Inkling 2 Mini | 44 synthetic regression questions | 2026-11-21, recorded in `555f5e4` | Default effort, 80 tokens, greedy, B200 vLLM | Exact route | **4/44**, 40 length-truncated | Same token cap as Qwen below. Effort and hardware differ. |
| Portfolio intent routing | Stock Inkling 2 Mini | Same 44 regression questions | 2026-11-21, recorded in `555f5e4` | Low effort, 512 tokens, greedy, B200 vLLM | Exact route | **41/44**, zero length-truncated | Longer budget and different effort. Compare with the 80-token row to see how the setup affects the result. |
| Portfolio intent routing | Qwen3-8B stock, broker SFT, and routing SFT | Same 44 synthetic questions, two per route | 2026-11-20, recorded in `784c8dd` | 80 tokens, greedy, RTX 4090 | Exact route | **38/44 each** | Same cap as Inkling's 80-token run. This is a routing regression set. |
| 2024 prepared evidence and unverified closes | Stock Inkling 2 Mini | 168 redacted broker cases + 24 synthetic unverified closes | 2026-11-21, saved B200 scorecard | Low effort, 512 tokens, greedy, B200 vLLM | Exact status and integer citations | **99/192**. Zero length-truncated. | Replay found 84 citation-type-only misses. Quoted IDs fail the exact metric. No false confirmations on the 24 synthetic unverified cases. |
| Expanded opening evidence | Stock Inkling 2 Mini | 48 synthetic holdout cases, 16 per status | 2026-11-21, saved scorecard | Low effort, 512 tokens, greedy, B200 vLLM | Exact status and citations | **45/48**. False support **0/32** expected unsupported cases. | All three misses hit the token cap. |
| Expanded evidence, targeted retry | Stock Inkling 2 Mini | The 3 length-truncated cases above | 2026-11-21, saved retry scorecard | Low effort, 1,024 tokens, greedy, B200 vLLM | Exact status and citations | **3/3**, zero length-truncated | Targeted retry only. |
| Frozen broker comparison | Stock Inkling vs step-12 LoRA | 186 private cases, 17 supported and 169 missing evidence | 2026-11-22, attempted | Greedy, 64 tokens, RTX PRO 6000 NeMo | Per-model exact, status recall, false support, and supported both-correct rate | **Not yet measured** | Original run stalled compiling kernels. Fixed-shape retry generated 12 stock replies and no matched batch. |
| External frozen broker review | Reported stock Inkling 2 Mini | 29 cases reported externally | 2026-11-22, review reference. GPU run date unverified. | Unverified | Reported exact score | **Unverified** | Original 29-case file, run settings, truncations, and false-support denominator were unavailable. This is distinct from the local 186-case frozen set. |
| H100 serving smoke test | Stock Inkling 2 Mini | 1 synthetic evidence request | 2026-11-21, saved scorecard | Low effort, 1,024 tokens, greedy, H100 SXM vLLM | Exact status and citations | **1/1** | Startup and one response only. |
| L4 serving smoke test | Stock Inkling 2 Mini GGUF | 1 synthetic route | 2026-11-22, saved scorecard | 512 tokens, temperature 0, effort unset, L4 llama.cpp | Exact route | **1/1** | Quantized inference startup and one response only. |
| Site compound query smoke test | Hosted stock Inkling + browser ledger | 1 synthetic two-ticker question | 2026-11-22, deployed Site test | L4 llama.cpp, 512-token planner cap | Expected plan and browser totals | **Passed** | Validates one hosted workflow. Earlier cold starts failed. |
| Synthetic lot pilot | Qwen3-8B stock, SFT, GRPO | 48 synthetic cases, 24 supported and 24 missing | 2026-11-19, recorded in `5871509` | Greedy, 80 tokens, RTX 4090 | Exact status and citations | **19/48**, **37/48**, **31/48** respectively | GRPO improved missing-evidence detection and lost supported matches. |
| October opening evidence | Qwen3-8B stock and SFT | 53 selected private cases, same prompt format | 2026-11-19, saved scorecard | Greedy, 80 tokens, local CPU llama.cpp Q4_0 | Exact status and citations | Stock **32/53**, SFT **53/53** | Small, selected clean cases. |
| 2025 broker-link evidence | Qwen3-8B stock, previous SFT, new SFT | 54 selected redacted cases, held out by instrument, same format | 2026-11-20, recorded in `e553653` | RTX 4090 pilot, decoding unlogged | Exact status and aliases | **0/54**, **11/54**, **54/54** respectively | Small same-format task. The October set uses a different prompt and split. |
| Hard private opening evidence | Qwen3-8B SFT | 196 private cases, 64 supported, 130 missing, 2 ambiguous | 2026-11-19, saved scorecard | Greedy, 80 tokens, local GGUF | Exact status and citations | **140/196**, including 58/64 supported, 80/130 missing, 2/2 ambiguous. False support **43/132** expected unsupported cases. | The ambiguity subset has two cases. |
| Hard private opening evidence replay | Deterministic ledger gate | Same 196 private cases | 2026-11-19, saved replay | No decoding, CPU | Rule agreement | **196/196** by construction because the gate also defines the labels. False support **0/132** expected unsupported cases. | Rule consistency check against the same labels. |
| Balanced hard lot pilot | Qwen3-8B stock, previous SFT, new SFT, SFT + GRPO | 60 synthetic holdouts, 20 per status | 2026-11-19, recorded in `5e293d2` | Greedy, 80 tokens, RTX 4090 | Exact status and citations | **21/60**, **19/60**, **26/60**, **25/60** respectively | GRPO had zero exact supported answers. |
| Close routing, model-only with candidates | Qwen3-8B stock and SFT | 30 private questions | 2026-11-19, saved scorecard | Greedy, 80 tokens, local GGUF | Exact operation and close ID | Stock **17/30**, SFT **18/30** | Candidate lists provided to the model. |
| Close resolution, ledger-assisted | Qwen3-8B stock or SFT + local filter resolution | Same 30 questions, no candidate list in prompt | 2026-11-19, saved scorecard | Greedy, 128 tokens, local GGUF + deterministic lookup | Exact operation and close ID after lookup | **26/30 each** | Model extracts filters. The ledger resolves them. |
| Portfolio, model-only synthesis | Qwen3-8B SFT | 20 questions, 40 possible rubric points | 2026-11-19, saved scorecard | Local GGUF Q4_0, decoding cap unlogged | Rubric points | **27/40** | Prepared evidence. Tax amounts were unavailable. |
| Portfolio, scripted lookup | Ledger, no model | Same 20-question rubric | 2026-11-20, saved scorecard | No decoding, CPU | Rubric points | **33/40** | Predefined queries and local lookup. Different execution path from model-only synthesis. |

> **Benchmark glossary**
>
> - **Verifier** checks ledger facts or evidence. A **scorer** compares a response
>   with the expected outcome. A **benchmark** combines the cases, runtime
>   settings, and scorer. A **holdout** is a split withheld from training and
>   used for evaluation. A validation holdout can select a checkpoint. A test
>   holdout stays separate from that choice.
> - **Exact** requires the expected status and integer citation IDs on lot
>   tasks, or the expected route key on routing tasks. **Status-only** checks
>   the label alone. **Status recall** divides correct predictions of a
>   status by the number of cases whose expected status is that label.
> - **False-support rate** divides incorrect supported predictions by the
>   number of cases with an expected non-supported status. For the paired
>   comparison, the denominator uses only matched unsupported cases.
> - **Supported both-correct rate** is the share of matched supported cases
>   both models answer exactly. Report it alongside each model's exact
>   accuracy, status recall, and false-support rate.
> - **Teacher-forced NLL** averages the negative log probability of expected
>   answer tokens while supplying the earlier expected tokens as context.
>   It measures a known answer's likelihood.

See [evaluation protocols](docs/evals.md), [training and recovery](docs/training.md),
and the [portfolio rubric](PORTFOLIO_QUESTION_BENCHMARK.md).

## Quickstart

Use Python 3.11 or newer. The ledger CLI uses the standard library.

```bash
python -m pip install .
ledger-review private/inputs/transactions.csv   --realized private/inputs/realized.csv --year 2026   --date-basis effective --format json --output ledger-report.json
python -m unittest discover
```

The CLI requires an explicit output path outside a `private` directory.
Choose a location you control because the report contains financial data.
It records source-file hashes, row counts, date basis, and package version.
Exit codes are 0 for clean output, 1 for a completed report with unresolved
evidence or rejected rows, and 2 for invalid input or a failed invariant.

Effective reporting uses the transaction date and broker Transaction Closed
Date when supplied. Posted mode uses Posted Date and broker Closed Date.
The report preserves both source dates. Use the broker's tax statement for
its reported tax period.

## Query a portfolio report

Generate a browser-readable report from transactions, realized lots, and a
dated holdings export. Adjust the period and snapshot date to your records.

```bash
python portfolio_review.py private/inputs/transactions.csv   private/inputs/realized.csv private/inputs/holdings.csv   --month 2026-11 --as-of 2026-11-19 --output private/portfolio-report.json
```

Load the file with **Load portfolio report** in the private Site. Try a
built-in query, or ask for unrealized P&L and dividends across tickers covered
by the report. The Site sends the question text to hosted Inkling. The JSON
and calculated dollars stay in the browser. An L4 cold start can take several
minutes. Coverage dates and unresolved records remain visible in the answer.

`portfolio_review.py --config configs/portfolio-example.json` selects target
symbols and evidence scopes. The CLI uses holdings underlyings by default.
See the [broker import and reporting workflow](docs/workflow.md) for options
and limitations.

## Data handling

Keep brokerage exports, derived reports, tax documents, private holdouts,
and checkpoints outside Git. The historical commands use the ignored
`private/` and `artifacts/` folders. The hosted model interprets queries.
The ledger remains the source for calculations and unresolved status.

Schwab is the first supported CSV integration. See [broker export coverage](docs/workflow.md#broker-integrations) and the [production ledger spec](PRODUCTION_LEDGER_SPEC.md).
