"""Score an OpenAI-compatible GPU model on the portfolio routing holdout."""

import argparse
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collections import Counter

from broker_training_examples import make_examples
from portfolio_training import routing_cases, score_route


def lot_holdout(path):
    cases = json.loads(path.read_text(encoding="utf-8"))["eval"]
    synthetic = [
        {"instrument": f"synthetic-{index}",
         "open_evidence": {"status": opening},
         "close_evidence": {"status": closing}}
        for index, (opening, closing) in enumerate(
            (opening, closing)
            for _ in range(3)
            for opening in ("quantity_match", "single_row_partial", "missing", "quantity_shortfall")
            for closing in ("missing", "unresolved")
        )
    ]
    return cases + [row for split in make_examples(synthetic).values() for row in split]


def score_lot(reply, case):
    try:
        answer = json.loads(reply)
    except ValueError:
        return False
    if not isinstance(answer, dict) or answer.get("status") != case["expected_cash"]:
        return False
    lines = answer.get("source_lines")
    return (isinstance(lines, list) and all(type(line) is int for line in lines)
            and sorted(lines) == case["expected_lines"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--startup-timeout", type=int, default=900)
    parser.add_argument("--max-tokens", type=int, default=80)
    parser.add_argument("--reasoning-effort", choices=["none", "low", "medium", "high"])
    parser.add_argument("--lot-holdout", type=Path)
    args = parser.parse_args()
    key = os.environ["PORTFOLIO_BENCHMARK_API_KEY"]

    def request(path, payload=None):
        command = ["curl", "--silent", "--show-error", "--max-time", "90", "--config", "-",
                   "--write-out", "\n%{http_code}", args.base_url.rstrip("/") + path]
        if payload is not None:
            command.extend(("--data-binary", json.dumps(payload)))
        config = 'header = ' + json.dumps(f"Authorization: Bearer {key}") + '\n'
        config += 'header = "Content-Type: application/json"\n'
        result = subprocess.run(command, input=config, capture_output=True, text=True, check=True)
        body, _, status = result.stdout.rpartition("\n")
        return int(status), body

    deadline = time.monotonic() + args.startup_timeout
    while True:
        try:
            status, body = request("/models")
        except subprocess.CalledProcessError:
            status, body = 0, ""
        if status == 200:
            available = {model["id"] for model in json.loads(body)["data"]}
            if args.model not in available:
                raise RuntimeError("Endpoint does not advertise the requested model")
            break
        if status == 401:
            raise RuntimeError("The model server rejected the benchmark API key")
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Model server startup timed out (HTTP {status})")
        time.sleep(5)

    print("Model server ready", flush=True)
    cases = lot_holdout(args.lot_holdout) if args.lot_holdout else routing_cases("eval", 44)

    def evaluate(case):
        payload = {
            "model": args.model, "messages": [{"role": "user", "content": case["question"]}],
            "temperature": 0, "max_tokens": args.max_tokens,
        }
        if args.reasoning_effort is not None:
            payload["reasoning_effort"] = args.reasoning_effort
        status, body = request("/chat/completions", payload)
        if status != 200:
            raise RuntimeError(f"Completion request failed (HTTP {status}): {body[:200]}")
        choice = json.loads(body)["choices"][0]
        reply = choice["message"].get("content") or ""
        correct = (score_lot(reply, case) if args.lot_holdout
                   else score_route(reply, [], case["expected_cash"]))
        return {"reply": reply, "target": case["expected_cash"], "finish_reason": choice["finish_reason"],
                "score": int(correct)}

    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(evaluate, cases))
    result = {"model": args.model, "correct": sum(row["score"] for row in replies),
              "total": len(replies), "max_tokens": args.max_tokens,
              "reasoning_effort": args.reasoning_effort, "replies": replies}
    if args.lot_holdout:
        totals = Counter(row["target"] for row in replies)
        correct_by_status = Counter(row["target"] for row in replies if row["score"])
        result["by_status"] = {label: {"correct": correct_by_status[label], "total": total}
                               for label, total in sorted(totals.items())}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['correct']}/{result['total']}", flush=True)


if __name__ == "__main__":
    main()
