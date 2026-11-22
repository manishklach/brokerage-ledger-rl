"""Reproduce the 100-case teacher-forced Inkling validation scorecard."""

import argparse
import json
import math
from pathlib import Path

import torch
import yaml
from nemo_automodel.components.config._arg_parser import parse_args_and_load_config
from nemo_automodel.components.datasets.utils import default_collater
from nemo_automodel.components.datasets.llm.chat_dataset import ChatDataset
from nemo_automodel.recipes.llm.train_ft import TrainFinetuneRecipeForNextTokenPrediction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--checkpoints", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists():
        parser.error("Choose a new output path")
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = yaml.safe_load(args.recipe.read_text(encoding="utf-8"))
    raw["checkpoint"].pop("restore_from", None)
    raw["checkpoint"]["checkpoint_dir"] = str(out.with_suffix(".runtime"))
    cases = json.loads(args.validation.read_text(encoding="utf-8"))
    validation_path = out.with_suffix(".answers.jsonl")
    with validation_path.open("w") as stream:
        for case in cases:
            answer = {"status": case["expected_cash"], "source_lines": case["expected_lines"]}
            messages = [{"role": "user", "content": case["question"]},
                        {"role": "assistant", "content": json.dumps(answer)}]
            stream.write(json.dumps({"messages": messages}) + "\n")
    config = out.with_suffix(".yaml")
    config.write_text(yaml.safe_dump(raw, sort_keys=False))
    trainer = TrainFinetuneRecipeForNextTokenPrediction(parse_args_and_load_config(str(config), argv=[]))
    trainer.setup()
    model = trainer.model_parts[0]
    model.eval()
    dataset_kwargs = {key: value for key, value in raw["dataset"].items() if key != "_target_"}
    dataset_kwargs.update(path_or_dataset_id=str(validation_path), shuffle_seed=None, tokenizer=trainer.tokenizer)
    dataset = ChatDataset(**dataset_kwargs)
    assert len(dataset) == len(cases) == 100
    batches = [default_collater([dataset[i] for i in range(start, min(start + 4, len(dataset)))])
               for start in range(0, len(dataset), 4)]
    checkpoints = {"stock": None, **{str(step): args.checkpoints / f"epoch_0_step_{step-1}/model"
                                      for step in (4, 8, 12)}}
    with out.open("x", encoding="utf-8") as stream, torch.no_grad():
        for name, checkpoint in checkpoints.items():
            if checkpoint is None:
                params = [p for n, p in model.named_parameters() if ".lora_B." in n]
                assert params and all(not torch.count_nonzero(p.to_local() if hasattr(p, 'to_local') else p).item() for p in params)
            else:
                trainer.checkpointer.load_model(model, str(checkpoint))
            nll, count = 0.0, 0
            for batch in batches:
                ids = batch["input_ids"].cuda()
                labels = batch["labels"].cuda()
                if "loss_mask" in batch:
                    labels.masked_fill_(~batch["loss_mask"].cuda().bool(), -100)
                logits = model(input_ids=ids, padding_mask=batch["padding_mask"].cuda())
                selected = labels != -100
                nll += torch.nn.functional.cross_entropy(logits[selected].float(), labels[selected], reduction="sum").item()
                count += selected.sum().item()
            assert count > 0 and math.isfinite(nll)
            result = {"checkpoint": name, "cases": len(cases), "assistant_tokens": count, "mean_nll": nll / count}
            stream.write(json.dumps(result) + "\n")
            stream.flush()
            print("VALIDATION_RESULT", json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
