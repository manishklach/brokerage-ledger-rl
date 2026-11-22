# Training and checkpoint recovery

See the [canonical benchmark table](../README.md#benchmarks) for scores, run settings, and limits.

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
LoRA adapters.

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

### Qwen portfolio routing pilot

This historical run trained on 264 synthetic prompts and evaluated on the
44-question routing regression split. The task classifies intent using the
provided catalog.

```bash
python train_pilot.py --task portfolio-route --train-count 264 --eval-count 44 --sft-steps 160 --rl-steps 0 --output artifacts/portfolio-route
```

### Inkling routing training data

The first Inkling adapter targets lot evidence. The separate routing exporter
is available for experiments on portfolio query selection.
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

### Inkling lot-evidence LoRA on one RTX PRO 6000

Generate the targeted synthetic training split and independent validation
split with:

```powershell
python prepare_inkling_lot_sft.py --output private/inkling-targeted-lot-sft
```

The generator produces 400 training and 100 validation examples. It
covers single-row partial fills, missing opening dates, quantity
shortfalls, exact fills, and ambiguous allocations. Validation uses a
separate seed and year. The broker holdout is excluded from training
and checkpoint selection.

A single 96 GB RTX PRO 6000 Blackwell completed one text-only LoRA step
and then reloaded that checkpoint to finish a 12-step pilot. The run used
NeMo AutoModel at `46fa6a5`, BF16 parameters, rank-8 attention adapters,
one example per step, and a 1,024-token sequence limit. The first smoke
test and the resumed pilot cost an estimated $0.28 and $0.33 in GPU time.
The earlier B200 attempt ended during container extraction.

The recorded [smoke recipe](../configs/inkling/rtx6000-smoke.yaml) and
[resume recipe](../configs/inkling/rtx6000-resume.yaml) use the same base
model and resume from the first saved checkpoint. The original runner
used the NVIDIA NeMo AutoModel 26.10 container pinned to
`sha256:0e4279f2740b4de9c3884f5d434d1a1520057c825f8a28d1e66dd16515451e9c`,
with the AutoModel source checkout at
`46fa6a505910a1e3c9bf58930b89047a7b6d748c` on `PYTHONPATH`.
The run recorded Transformers 5.18.0 and PyTorch
`2.14.0a0+4fdf77b940.nv26.08` with CUDA 13.4.

To reproduce the short training run on a compatible Linux GPU, make
the project checkout available as `/workspace/ledger` and the pinned
AutoModel checkout as `/workspace/automodel`. Run from the AutoModel
checkout so the relative chat-template path resolves. Use fresh output
directories if repeating an existing run.

```bash
export PYTHONPATH=/workspace/automodel
export HF_HOME=/workspace/hf
cd /workspace/automodel
python /workspace/ledger/prepare_inkling_lot_sft.py --output /workspace/data
automodel /workspace/ledger/configs/inkling/rtx6000-smoke.yaml --nproc-per-node 1
automodel /workspace/ledger/configs/inkling/rtx6000-resume.yaml --nproc-per-node 1
```

The recipe dequantizes the released checkpoint into BF16 for training.
It applies LoRA to the attention projections and keeps the expert
weights frozen. The pilot reached about 51 GiB peak GPU memory in the
recorded resumed-step logs. NeMo names checkpoints by zero-based
step index, so `epoch_0_step_11` is the adapter after 12 optimizer steps.


The checkpoint selection results are in the canonical table.

This is **teacher-forced negative log likelihood**. Step 12 was chosen
solely by this metric, with the expected preceding tokens supplied.
Lower NLL after SFT is expected. The table supplies no generated-answer
accuracy, status-recall, or false-support result.

Reproduce the table from the pinned AutoModel checkout after running the
training commands above. Keep the output and checkpoint files private.

```bash
python /workspace/ledger/evaluate_inkling_validation_nll.py \
  --recipe /workspace/ledger/configs/inkling/rtx6000-smoke.yaml \
  --validation /workspace/data/validation.json \
  --checkpoints /workspace/inkling-resume \
  --output /workspace/ledger/private/inkling-validation-scorecard.jsonl
```

Exact generated answers and false support require a separate comparison
with the same prompts, decoding settings, and scorer. The available
private broker set contains 186 cases and differs from the 29-case set
described in external feedback. Neither comparison has produced results
yet. Keep the original reports and holdouts private.

`evaluate_inkling_checkpoint.py` is the native NeMo comparison runner.
Provide the original single-GPU training recipe, the adapter's `model/`
directory, a private frozen holdout, and a new output path. It uses greedy
decoding with the same 64-token limit for both variants. It writes a batch
only after both variants finish, so an interrupted run retains paired
replies. Summarize the completed pairs with:

```bash
python summarize_inkling_generation.py private/inkling-broker-generation.jsonl
```

The headline supported both-correct rate counts cases where both models return the
exact answer, divided by the number of matched **supported** cases.
The summary gives per-model exact accuracy, status recall, and truncation
separately for supported and unsupported cases. False-support rate uses
matched unsupported cases as its denominator. Unpaired replies are
counted separately.

A GPU smoke test exposed repeated FlexAttention compilation as
the decode sequence grew. The fixed-shape retry generated the stock
half of the first batch before the runtime limit. No paired scores were
produced.

The pod was stopped after the run. Its persistent disk was tied to
the original host, and Runpod could not allocate that GPU for recovery.
The pod was restarted with CPUs and all four checkpoints were archived,
including the optimizer state, recipes, and validation results. The
local archive matched the SHA-256 digest computed on the pod. The pod
and its 45 GB disk were then deleted. The archive is kept in the
ignored `private/` directory and is excluded from GitHub and release
downloads. The hosted L4 Site serves the stock model.
