# Production ledger hardening

Implementation order is settlement and input recovery, date consistency, configurable portfolio review, regression coverage, then CLI and audit guarantees. The ledger owns every calculation and every decision about evidence. The model may interpret a question or explain a verified result. An unresolved ledger result remains unresolved in the UI.

## 1. Continue processing when evidence is incomplete

Today the matcher can consume a full settlement or a partial settlement backed by one open lot. A partial settlement across multiple lots can block the remainder of that side. Unsupported events can block both sides.

- Allocate a known partial settlement to the oldest eligible open lots on the affected contract and side. Prefer explicit broker lot references when present. Use effective opening date and original input order as the FIFO tie-breaker when the feed establishes that order. Record each consumed lot, quantity, source row, and the FIFO assumption. Keep any broker-reported tax-lot result distinguishable from a modeled allocation.
- When direction, quantity, or event order is genuinely indeterminate, record the reason and skip the inventory mutation. Where the affected side is known, mark only that side and its dependent results unresolved. An opaque event goes in quarantine and flags the contract. Continue processing available evidence and mark any results that depend on unverified inventory as provisional.
- Record row-level parsing errors with file, row number, field, and reason. Continue with valid rows. Treat an unreadable file or missing required headers as file-level invalid input. Never include the entire rejected row by default.

Acceptance tests:

- Two open lots of 3 and 5 contracts, followed by settlement of 4, consume 3 and 1. The remaining 4 retain their original lot lineage and can be closed. Repeat with the short side. Verify settlement and close quantities and prevent double counting of cash.
- A settlement with insufficient inventory or unknown side records a reason. A subsequent transaction on an unaffected side and a subsequent transaction on a different contract still produce results.
- A valid row, malformed amount, then valid row produces two accepted rows and one warning with the source line. An unreadable CSV or missing required headers fails at file level.
- The full private five-year run completes and reports unresolved events by reason and affected scope. Every remaining blocker points to a genuine input or evidence problem. Completion requires full five-year source coverage so missing months cannot look clean.

## 2. Use one date basis

Today some close comparisons use effective dates while annual realized totals use broker Closed Date and monthly cash uses posted dates.

- Define one date-basis selector shared by the ledger, lot matcher, reconciliation, and period and portfolio reporting. Default to effective for library and CLI callers. For transactions, choose Effective Date or Posted Date. For realized lots, use Transaction Closed Date when supplied for effective reporting and broker Closed Date for posted reporting. Preserve both source dates.
- Apply the selector to cash-flow buckets, realized-lot inclusion, reconciliation matching, and report period keys. Show the holdings snapshot date explicitly. Preserve the broker's tax-reporting period when shown as independent source evidence.
- Sum the same eligible realized rows and monetary fields across monthly and annual views with Decimal arithmetic. Raise a reconciliation failure if the sums differ, including the year, field, and difference.

Acceptance tests:

- A December 31 close posted January 2 lands in December and the prior annual total in effective mode. It lands in January and the following annual total in posted mode. Trade matching, monthly summary, and annual report agree in both modes.
- Missing Transaction Closed Date falls back to Closed Date. A deliberately mismatched monthly aggregate fails verification.

## 3. Move portfolio-specific choices into configuration

- Define a validated, versioned configuration for tickers, snapshot date, reporting periods, and saved questions. Each saved question names a generic evidence query and its parameters. Keep the existing tracked funds and sample questions in an example config. Use a neutral default for new portfolios.
- Route configured questions through the existing report evidence and source-line structures. A missing input produces a scoped missing-evidence result. Free-form question support can grow through new generic evidence queries.

Acceptance tests:

- Run the same engine against two fixtures with different tickers and months using different configs. No code changes are needed and no example symbols leak into unrelated output.
- Invalid metric names and dates fail validation. Empty ticker lists and missing snapshots produce explicit statuses.

## 4. Add production regression coverage

- Establish a synthetic golden fixture in public CI. Canonicalize ordering, decimal strings, and date formatting before hashing. Commit only a digest and fixture metadata for the private history. Run that regression on an explicitly configured private runner or locally with authorized access. A public CI run cannot validate inputs it cannot read.
- Add generated cases for rolls, partial fills and settlements, expirations, assignments, and wash flags. Check contract quantity conservation by side and cash conservation by currency, including fees. Count underlying settlement cash and share movements once. Keep broker wash-sale adjustments labeled separately from cash.
- Exercise the parser with required columns missing, parenthesized negatives, dates with an as-of component, invalid values, and duplicate rows. Retain legitimate identical fills unless stable broker IDs establish duplication. Flag uncertain duplicates and verify handling of overlapping exports.

Acceptance tests:

- Repeated runs on the same fixture produce the same digest. A deliberate one-cent change fails. Public fixtures contain synthetic data only.
- Hundreds of seeded trials conserve cash and quantity, and no trial emits negative residual open inventory.
- Malformed records produce bounded diagnostics. The parser never silently treats an invalid amount as zero.

## 5. Package the CLI and preserve an audit trail

- Add an installable ledger-review entry point. Declare runtime dependencies in pyproject.toml, with GPU training dependencies kept separate. Support --date-basis effective|posted, --output, and --format json. Return 0 for a clean report, 1 for a completed report with unresolved blockers, and 2 for invalid input or failed invariants.
- Record package and schema versions, input basenames, file digests, accepted and rejected row counts, date basis, period, and configuration digest in the report. The private golden check excludes volatile fields such as elapsed time.
- Write only to an explicit output path. Reject paths that resolve to an input or into the project's protected private input tree, including aliases and symlinks. Keep generated private reports in an explicitly selected output directory outside that protected tree. Write the completed report atomically and leave source exports byte-for-byte intact.

Acceptance tests:

- Build a wheel, install it in a clean environment, and invoke ledger-review from outside the checkout. Verify exit codes 0, 1, and 2 and the audit metadata.
- Attempts to overwrite an input or write under the protected private input tree fail without changing a file. Verify source hashes before and after a successful run.
- An unresolved answer remains visible as unresolved even when the model is connected. No model-generated number replaces a blocked ledger calculation.
