"""Compare stock and LoRA Inkling by generating exact lot-evidence answers."""

import argparse
import random
import json
from pathlib import Path

import torch
import yaml
from nemo_automodel.components.config._arg_parser import parse_args_and_load_config
from nemo_automodel.recipes.llm.train_ft import TrainFinetuneRecipeForNextTokenPrediction

from evaluate_portfolio_server import lot_answer, score_lot

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = json.loads(args.holdout.read_text(encoding="utf-8"))
    supported, unsupported = [], []
    for index, row in enumerate(rows):
        target = supported if row["expected_status"] == "supported" else unsupported
        target.append(dict(case=index, status=row["expected_status"],
                           lines=row["expected_lines"], prompt=row["question"]))
    rng = random.Random(20261122)
    rng.shuffle(supported)
    rng.shuffle(unsupported)
    pairs = min(len(supported), len(unsupported))
    cases = [row for pair in zip(supported[:pairs], unsupported[:pairs], strict=True) for row in pair]
    cases.extend(supported[pairs:] + unsupported[pairs:])
    if not cases:
        parser.error("The holdout is empty")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = yaml.safe_load(args.recipe.read_text(encoding="utf-8"))
    raw["checkpoint"].pop("restore_from", None)
    raw["checkpoint"]["checkpoint_dir"] = str(args.output.resolve().with_suffix(".runtime"))
    config = args.output.resolve().with_suffix(".yaml")
    config.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    trainer = TrainFinetuneRecipeForNextTokenPrediction(parse_args_and_load_config(str(config), argv=[]))
    trainer.setup()
    model = trainer.model_parts[0]
    model.eval()
    tok = trainer.tokenizer
    tok.padding_side = "left"
    adapter = args.adapter
    end_ids = [tok.convert_tokens_to_ids(t) for t in ("<|end_message|>", "<|content_model_end_sampling|>")]
    assert all(isinstance(i, int) and i != tok.unk_token_id for i in end_ids)
    stop_ids = torch.tensor(end_ids, device="cuda")
    b_params = [p for n, p in model.named_parameters() if ".lora_B." in n]
    assert b_params

    batch_size, max_new_tokens = 12, 64
    for case in cases:
        prompt = tok.apply_chat_template(
            [{"role": "user", "content": case["prompt"]}], tokenize=False
        ) + "<|message_model|><|content_text|>"
        case["tokens"] = tok.encode(prompt, add_special_tokens=False)
    prompt_width = max(len(case["tokens"]) for case in cases)
    decode_width = prompt_width + max_new_tokens

    @torch.no_grad()
    def generate(batch):
        # Inkling's FlexAttention compiles for static dimensions. Reserve the
        # entire output buffer so later tokens reuse the same compiled graph.
        ids = torch.full((batch_size, decode_width), tok.pad_token_id, dtype=torch.long, device="cuda")
        valid = torch.zeros_like(ids, dtype=torch.bool)
        for row, case in enumerate(batch):
            tokens = case["tokens"]
            ids[row, prompt_width - len(tokens):prompt_width] = torch.tensor(tokens, device="cuda")
            valid[row, prompt_width - len(tokens):prompt_width] = True
        # Keep a valid prompt in padded batch slots to avoid wholly masked rows.
        ids[len(batch):] = ids[0]
        valid[len(batch):] = valid[0]
        finished = torch.arange(batch_size, device="cuda") >= len(batch)
        tokens = []
        position = torch.empty(1, dtype=torch.long, device="cuda")
        for index in range(prompt_width, decode_width):
            positions = (valid.long().cumsum(-1) - 1).clamp_min(0)
            position.fill_(index - 1)
            logits = model(input_ids=ids, padding_mask=~valid, position_ids=positions, logits_to_keep=position)
            next_id = torch.where(finished, stop_ids[0], logits[:, -1].argmax(-1))
            tokens.append(next_id[:len(batch)])
            ids[:, index] = next_id
            valid[:, index] = ~finished
            finished |= torch.isin(next_id, stop_ids)
            if finished.all().item():
                break
        replies = tok.batch_decode(torch.stack(tokens, dim=1).cpu(), skip_special_tokens=True)
        return zip(replies, finished[:len(batch)].tolist(), strict=True)

    with args.output.open("x", encoding="utf-8") as stream, torch.no_grad():
        for offset in range(0, len(cases), batch_size):
            batch = cases[offset:offset + batch_size]
            paired = []
            for variant in ("stock", "step12"):
                if variant == "stock":
                    for p in b_params:
                        p.zero_()
                else:
                    trainer.checkpointer.load_model(model, str(adapter))
                results = []
                for case, (reply, stopped) in zip(batch, generate(batch), strict=True):
                    status = lot_answer(reply).get("status")
                    results.append({
                        "case": case["case"], "target": case["status"], "variant": variant,
                        "reply": reply, "correct": int(score_lot(reply, {"expected_cash":case["status"],"expected_lines":sorted(case["lines"])})),
                        "predicted_status": status, "truncated": not stopped,
                    })
                paired.extend(results)
                print("GENERATION_VARIANT", offset, variant, len(results), flush=True)
            stream.writelines(json.dumps(row) + "\n" for row in paired)
            stream.flush()
            print("MATCHED_CASES", offset + len(batch), flush=True)



if __name__ == "__main__":
    main()
