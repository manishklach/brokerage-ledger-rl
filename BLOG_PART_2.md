# Part 2 — Training Inkling on one GPU and testing what it learned

[Part 1](BLOG.md) describes the ledger, the first model experiments, and the hosted portfolio workspace. Here I wanted to answer a narrower question. Could I train Inkling to tell whether the opening rows actually support an options close, on hardware I could afford to rent?

## The cases I wanted it to learn

An options close can reference quantities from several opening dates. For each requested date, the ledger checks the date and side and adds up the eligible recorded quantity. One larger row can support a smaller allocation. Two or more eligible rows with excess quantity can leave the choice of lots ambiguous. If any date is short, the claim lacks evidence even if another date has plenty of quantity.

I built 400 synthetic training examples and 100 separate validation examples. Both splits include partial allocations from a single row, missing dates, quantity shortfalls, exact fills, and ambiguous allocations. They use different random seeds and calendar years. The ledger derives the status and citations. The private broker holdout stays out of both splits.

## What worked on the GPU

The first B200 spent eight minutes unpacking the container image. I stopped it before the model loaded. The next attempt used a 96 GB RTX PRO 6000 Blackwell. On that host the image started and the model downloaded. I used NeMo AutoModel to run a text-only LoRA recipe with BF16 base weights, rank-8 updates to attention projections, a 1,024-token sequence limit, and one example per optimization step.

I saved the first checkpoint and resumed from it in a separate session. The pilot ran to 12 steps and saved adapters at steps 4, 8, and 12. GPU time for the initial RTX smoke test and the resumed run came to roughly $0.28 and $0.33, respectively. These are estimates for those short sessions. They include startup overhead and do not establish a stable cost for a longer training run.

## What the validation result means

I ran stock Inkling and each adapter on the same 100 synthetic validation cases in the same runtime. Each variant was scored on the same 2,252 answer tokens.

| Variant | Mean negative log likelihood per answer token |
| --- | ---: |
| Stock | 1.1473 |
| Step 4 | 0.2941 |
| Step 8 | 0.1801 |
| Step 12 | 0.1638 |

The step-12 checkpoint assigned the most probability to the expected answer tokens. The scoring pass provides the correct preceding tokens, so it measures how the model scores a known answer. An open-ended run has to generate the status and citations itself, where an early mistake can change everything that follows.

I tried to run that matched generation test on the private 186-case broker set. The first decoder changed its tensor shape at every token, causing repeated FlexAttention compilation. A fixed-shape retry generated the stock half of the first 12-case batch before the budget cap. It produced no paired scores. For a fair comparison, I need both variants to answer the same cases, then count exact status and citation matches, recall by status, false claims of support, and truncation. The 186-case set is also distinct from the 29-case set mentioned in an external review.

## What survived the shutdown

Stopping the pod freed the GPU but left the disk tied to its host. When the GPU was unavailable, I restarted the pod using CPUs, packaged the four checkpoints, optimizer state, recipe files, and validation scorecard, then verified the local archive against the remote SHA-256 digest. I removed the temporary pod and disk after that check. The backup stays local.

The hosted portfolio workspace still serves stock Inkling on an on-demand L4. It uses a query plan to identify tickers, metrics, and dates. The browser reads the report and computes the figures. The new adapter is a separate experiment in judging opening evidence. A matched benchmark on held-out broker cases is the test that will determine whether it improves that job.

[Training recipes and reproduction details](README.md#inkling-lot-evidence-lora-on-one-rtx-pro-6000)
