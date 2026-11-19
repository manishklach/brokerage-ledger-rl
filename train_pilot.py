"""Run baseline, supervised fine-tuning, then GRPO with executable rewards."""

import argparse
import json
from pathlib import Path

from lot_pilot_data import hard_lot_cases, lot_cases, score_lot
from pilot_data import cases
from rewards import score_spread


def evaluate(model, tokenizer, examples, scorer):
    import torch
    from torch.utils.data import DataLoader

    model.eval()
    scores = []
    details = []
    for batch in DataLoader(examples, batch_size=4, collate_fn=list):
        inputs = tokenizer(
            [row["prompt"] for row in batch], return_tensors="pt", padding=True,
            add_special_tokens=False,
        ).to(model.device)
        with torch.inference_mode():
            output = model.generate(
                **inputs, max_new_tokens=80, do_sample=False, temperature=None,
                top_k=None, top_p=None, pad_token_id=tokenizer.pad_token_id,
            )
        replies = tokenizer.batch_decode(output[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)
        for reply, row in zip(replies, batch, strict=True):
            score = scorer(reply, row["expected_lines"], row["expected_cash"])
            scores.append(score)
            details.append({"reply": reply, "target": row["expected_cash"], "score": score})
    return {"correct": int(sum(scores)), "total": len(scores)}, details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sft-steps", type=int, default=12)
    parser.add_argument("--rl-steps", type=int, default=8)
    parser.add_argument("--eval-count", type=int, default=16)
    parser.add_argument("--task", choices=["spread", "lot", "hard-lot"], default="spread")
    args = parser.parse_args()
    examples, scorer = {
        "spread": (cases, score_spread),
        "lot": (lot_cases, score_lot),
        "hard-lot": (hard_lot_cases, score_lot),
    }[args.task]

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, set_seed
    from trl import GRPOConfig, GRPOTrainer, SFTConfig, SFTTrainer

    set_seed(42)
    args.output.mkdir(parents=True, exist_ok=True)
    checkpoint = "Qwen/Qwen3-8B"
    tokenizer = AutoTokenizer.from_pretrained(checkpoint, padding_side="left")
    model = AutoModelForCausalLM.from_pretrained(
        checkpoint, torch_dtype=torch.bfloat16, device_map={"": 0},
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_quant_type="nf4",
        ),
    )

    def dataset(split, count):
        rows = []
        for example in examples(split, count):
            question = example.pop("question")
            prompt = tokenizer.apply_chat_template(
                [{"role": "user", "content": question}], tokenize=False,
                add_generation_prompt=True, enable_thinking=False,
            )
            rows.append({"prompt": prompt, "completion": example.pop("answer") + tokenizer.eos_token, **example})
        return rows

    train = dataset("train", 128)
    held_out = dataset("eval", args.eval_count)
    scorecard = {}

    def record(stage):
        scorecard[stage], details = evaluate(model, tokenizer, held_out, scorer)
        (args.output / f"{stage}-replies.json").write_text(json.dumps(details, indent=2))
        print(json.dumps({stage: scorecard[stage]}), flush=True)
        (args.output / "scores.json").write_text(json.dumps(scorecard, indent=2))

    record("stock")
    model = get_peft_model(prepare_model_for_kbit_training(model), LoraConfig(
        r=16, lora_alpha=32, target_modules="all-linear", task_type="CAUSAL_LM",
    ))
    sft = SFTTrainer(
        model=model, processing_class=tokenizer,
        args=SFTConfig(
            output_dir=str(args.output / "sft"), per_device_train_batch_size=2,
            max_steps=args.sft_steps, max_length=768, completion_only_loss=True,
            learning_rate=1e-4, logging_steps=1, bf16=True, report_to=[],
            save_strategy="no", gradient_checkpointing_kwargs={"use_reentrant": False},
        ),
        train_dataset=Dataset.from_list(train).select_columns(["prompt", "completion"]),
    )
    sft.train()
    sft.save_model(str(args.output / "sft"))
    del sft
    record("sft")

    def task_reward(completions, expected_lines, expected_cash, **kwargs):
        return [
            scorer(answer, lines, cash)
            for answer, lines, cash in zip(completions, expected_lines, expected_cash, strict=True)
        ]

    rl = GRPOTrainer(
        model=model, processing_class=tokenizer, reward_funcs=task_reward,
        args=GRPOConfig(
            output_dir=str(args.output / "rl"), max_steps=args.rl_steps,
            per_device_train_batch_size=4, num_generations=4, max_completion_length=80,
            learning_rate=1e-5, logging_steps=1, bf16=True, report_to=[],
            save_strategy="no", use_vllm=False, beta=0.0, temperature=0.9,
            gradient_checkpointing_kwargs={"use_reentrant": False},
        ),
        train_dataset=Dataset.from_list(train).select_columns(["prompt", "expected_lines", "expected_cash"]),
    )
    rl.train()
    rl.save_model(str(args.output / "rl"))
    record("rl")


if __name__ == "__main__":
    main()
