"""Run the trained evidence task on private cases with local model inference."""

import argparse
import json
from pathlib import Path

from lot_pilot_data import score_lot
from train_pilot import evaluate
from collections import defaultdict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("--model", type=Path, required=True, help="Local Qwen3-8B checkpoint folder")
    parser.add_argument("--sft", type=Path, required=True)
    parser.add_argument("--rl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    tokenizer = AutoTokenizer.from_pretrained(args.model, padding_side="left", local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, local_files_only=True, dtype=dtype, device_map={"": device},
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_compute_dtype=dtype, bnb_4bit_quant_type="nf4",
        ),
    )
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    examples = [{
        "prompt": tokenizer.apply_chat_template(
            [{"role": "user", "content": case["question"]}], tokenize=False,
            add_generation_prompt=True, enable_thinking=False,
        ),
        "expected_lines": case["expected_lines"],
        "expected_cash": case["expected_status"],
    } for case in cases]
    results = {}

    def record(name):
        summary, replies = evaluate(model, tokenizer, examples, score_lot)
        groups = defaultdict(lambda: {"correct": 0, "total": 0})
        for case, reply in zip(cases, replies, strict=True):
            reply["id"] = case["id"]
            counts = groups[case["expected_status"]]
            counts["correct"] += int(reply["score"])
            counts["total"] += 1
        results[name] = {**summary, "by_status": groups, "replies": replies}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(name, summary, flush=True)

    record("stock")
    model = PeftModel.from_pretrained(model, args.sft, adapter_name="sft")
    record("sft")
    model.load_adapter(args.rl, adapter_name="rl")
    model.set_adapter("rl")
    record("rl")


if __name__ == "__main__":
    main()
