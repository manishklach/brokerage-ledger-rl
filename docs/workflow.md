# Ledger and query workflow

See the [canonical benchmark table](../README.md#benchmarks) for scores, run settings, and limits.

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
4. In the private hosted workspace, type a free-form question and select
   **Run query**. For example, ask “What were the unrealized losses and
   recorded dividends for AAPL and MSFT in 2026? Show each ticker and the
   combined totals.” Use tickers and a year covered by your report.
   **Inkling connection** is available for a separate OpenAI-compatible
   Inkling server ending in `/v1` that allows requests from the Site origin.

The Site sends the question text to Inkling. For ticker-level P&L and
dividend queries, it validates the returned tickers, metrics, year, and
answer placeholder before calculating the figures in the browser.
Unrealized P&L is dated to the holdings snapshot. Dividend totals cover
the transaction dates shown and include recorded reinvested dividends.
The report now includes transaction rows, annual realized lots, and
holdings. Keep the JSON and source exports private.

The managed deployment uses stock Inkling 2 Mini in 4-bit GGUF format,
served by llama.cpp on Runpod Serverless. It has zero minimum workers,
allows one L4 on demand, and has a 15-second idle timeout. The Site source
is versioned separately in Sites. The canonical table records the hosted
smoke result.

The JSON comes from the CSVs and can be regenerated whenever they change.
Generating the report requires no model training. The hosted workspace is
private. The command above works independently of access to the workspace.

## Monthly portfolio review

The ledger defaults to effective dates for cash buckets, modeled closes,
and broker realized totals. Use `--date-basis posted` for the posted view.
The effective view uses Transaction Closed Date when the broker supplies
it and falls back to Closed Date. Both source dates remain in the report.
Reported realized amounts are reconciled across all months and the year.

`portfolio_review.py --config configs/portfolio-example.json` selects the
example's tickers and evidence scope. Without a config or `--tickers`,
the CLI uses the holdings underlyings. The numbered answers remain
compatible with the existing Site.

Install the project and run a read-only audit with the unified CLI:

```bash
python -m pip install .
ledger-review transactions.csv --realized realized.csv --year 2026 --date-basis effective --format json --output ledger-report.json
```

The CLI exits with 0 for a clean report, 1 for unresolved evidence or
rejected rows, and 2 for invalid input. It records source hashes and row
counts, refuses output paths inside a private directory or over a source
export, and writes the report atomically. Choose an existing output
directory that you control because the report contains financial data.

The `option_lots.py` CLI and Python `match_options()` API use the effective
month by default. Pass `--date-basis posted` in the CLI or
`date_basis="posted"` in Python for the posted-month view.

Unsupported option events affect provisional closes from their effective
date forward. The matcher scopes a blocker to the long or short inventory
when the action identifies the affected side. A signed expiration,
assignment, or exercise can remove all known remaining lots on a side
when its quantity ties and that side has no prior blockers. A partial
settlement on a clean side uses FIFO across eligible opening lots. Later
closes cite that settlement and use the remaining lot basis in provisional
P&L. Insufficient or previously unresolved inventory still requires
review. The matcher quarantines opaque events and flags later dependent
results. The holdings
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
scripted workflow uses numbered queries and automatic record lookup.

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
