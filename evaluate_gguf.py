"""Compare stock and supervised Qwen checkpoints in the same local GGUF runtime."""

import argparse
import ctypes
import json
from collections import Counter
from contextlib import closing
from pathlib import Path

from close_filters import FILTER_SCHEMA, parse_filters, resolve
from lot_pilot_data import score_lot
from query_benchmark import query_score


def evaluate(model, tokenizer, cases, *, query_cases=False, filter_index=None, grammar=None):
    replies = []
    correct_by_status = Counter()
    total_by_status = Counter()
    for case in cases:
        question = case["filter_prompt"] if filter_index is not None else case["question"]
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": question}], tokenize=False,
            add_generation_prompt=True, enable_thinking=False,
        )
        tokens = model.tokenize(prompt.encode(), add_bos=False, special=True)
        reply = model.create_completion(
            tokens, max_tokens=128 if filter_index is not None else 80, temperature=0.0, top_k=0, top_p=1.0,
            stop=["<|im_end|>", "<|endoftext|>"], grammar=grammar,
        )["choices"][0]["text"]
        status = case["expected_status"]
        if filter_index is not None:
            filters = parse_filters(reply)
            output = resolve(reply, filter_index)
            operation = output["operation"] == status
            close_id = output.get("close_id") == case["expected_close_id"]
            evidence = "expected_ledger" not in case or output.get("ledger") == case["expected_ledger"]
            score = int(operation and close_id and evidence)
            checks = {"filters_exact": filters == case["expected_filters"], "valid_filters": filters is not None,
                      "operation": operation, "close_id": close_id, "decision": output}
        elif query_cases:
            checks = query_score(reply, case)
            score = int(checks["exact"])
        else:
            checks = {}
            score = int(score_lot(reply, case["expected_lines"], status))
        correct_by_status[status] += score
        total_by_status[status] += 1
        replies.append({"id": case["id"], "reply": reply, "score": score, **checks})
        yield {
            "correct": sum(correct_by_status.values()),
            "total": len(cases), "completed": len(replies),
            "by_status": {
                label: {"correct": correct_by_status[label], "total": count}
                for label, count in total_by_status.items()
            },
            "replies": replies,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--sft", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--sft-only", action="store_true", help="Skip the stock checkpoint")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--query-cases", action="store_true")
    modes.add_argument("--filter-index", type=Path, help="Resolve extracted filters against this evidence index")
    args = parser.parse_args()

    import llama_cpp as cpp
    from transformers import AutoTokenizer

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not cases:
        parser.error("Expected at least one evaluation case")
    filter_index = None if args.filter_index is None else json.loads(args.filter_index.read_text(encoding="utf-8"))
    grammar = None if filter_index is None else cpp.LlamaGrammar.from_json_schema(FILTER_SCHEMA, verbose=False)
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results = {}

    with closing(cpp.Llama(
        model_path=str(args.model), n_ctx=4096, n_batch=256, n_threads=args.threads,
        n_threads_batch=args.threads, n_gpu_layers=0, verbose=False,
    )) as model:
        def record(stage):
            for result in evaluate(model, tokenizer, cases, query_cases=args.query_cases,
                                   filter_index=filter_index, grammar=grammar):
                results[stage] = result
                temporary = args.output.with_suffix(".tmp")
                temporary.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
                temporary.replace(args.output)
                completed = result["completed"]
                if completed % 4 == 0 or completed == len(cases):
                    print(f"{stage}: {completed}/{len(cases)}", flush=True)

        if not args.sft_only:
            record("stock")
        adapter = cpp.llama_adapter_lora_init(model._model.model, str(args.sft).encode())
        if not adapter:
            raise RuntimeError("Could not load the supervised GGUF adapter")
        try:
            pointers = (cpp.llama_adapter_lora_p_ctypes * 1)(adapter)
            scales = (ctypes.c_float * 1)(1.0)
            if cpp.llama_set_adapters_lora(model._ctx.ctx, pointers, 1, scales):
                raise RuntimeError("Could not attach the supervised GGUF adapter")
            model.reset()
            record("sft")
        finally:
            cpp.llama_set_adapters_lora(model._ctx.ctx, None, 0, None)
            cpp.llama_adapter_lora_free(adapter)


if __name__ == "__main__":
    main()
