"""Export synthetic chat examples for the next Inkling portfolio-routing fine-tune."""

import argparse
import json
from pathlib import Path

from portfolio_training import INTENTS, routing_cases


def export_splits(output):
    output.mkdir(parents=True, exist_ok=True)
    counts = {}
    for split, count in (("train", len(INTENTS) * 12), ("eval", len(INTENTS) * 2)):
        examples = routing_cases(split, count)
        path = output / f"{split}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for example in examples:
                messages = [
                    {"role": "user", "content": example["question"]},
                    {"role": "assistant", "content": example["answer"]},
                ]
                handle.write(json.dumps({"messages": messages}) + "\n")
        counts[split] = len(examples)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_splits(args.output), sort_keys=True))


if __name__ == "__main__":
    main()
