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
from inkling_evidence_holdout import evidence_cases, expanded_evidence_cases
from portfolio_training import routing_cases, score_route
from rewards import unique_fields


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


def lot_answer(reply):
    try:
        answer = json.loads(reply, object_pairs_hook=unique_fields)
    except ValueError:
        return {}
    return answer if isinstance(answer, dict) else {}


def score_lot(reply, case):
    answer = lot_answer(reply)
    if set(answer) != {"status", "source_lines"} or answer["status"] != case["expected_cash"]:
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
    dataset = parser.add_mutually_exclusive_group()
    dataset.add_argument("--lot-holdout", type=Path)
    dataset.add_argument("--fresh-evidence", action="store_true")
    dataset.add_argument("--expanded-evidence", action="store_true")
    args = parser.parse_args()
    key = os.environ.get("PORTFOLIO_BENCHMARK_API_KEY")
    if not key:
        parser.error("Set PORTFOLIO_BENCHMARK_API_KEY to the model server API key")

    def request(path, payload=None):
        command = ["curl", "--silent", "--show-error", "--max-time", "90", "--config", "-",
                   "--write-out", "\n%{http_code}", args.base_url.rstrip("/") + path]
        if payload is not None:
            command.extend(("--data-binary", json.dumps(payload)))
        config = 'header = ' + json.dumps(f"Authorization: Bearer {key}") + '\n'
        config += 'header = "Content-Type: application/json"\n'
        for delay in (0, 1, 2):
            if delay:
                time.sleep(delay)
            result = subprocess.run(command, input=config, capture_output=True, text=True)
            body, _, status_text = result.stdout.rpartition("\n")
            status = int(status_text) if result.returncode == 0 and status_text.isdigit() else 0
            if status and status not in {408, 429, 500, 502, 503, 504}:
                break
        return status, body

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
    if args.expanded_evidence:
        cases = expanded_evidence_cases()
    elif args.fresh_evidence:
        cases = evidence_cases()
    elif args.lot_holdout:
        cases = lot_holdout(args.lot_holdout)
    else:
        cases = routing_cases("eval", 44)
    evidence_eval = args.expanded_evidence or args.fresh_evidence or args.lot_holdout is not None

    def evaluate(case):
        payload = {
            "model": args.model, "messages": [{"role": "user", "content": case["question"]}],
            "temperature": 0, "max_tokens": args.max_tokens,
        }
        if args.reasoning_effort is not None:
            payload["reasoning_effort"] = args.reasoning_effort
        started = time.perf_counter()
        result = {"case_id": case.get("id"), "target": case["expected_cash"]}
        try:
            status, body = request("/chat/completions", payload)
            if status != 200:
                return {**result, "score": 0, "error": f"HTTP {status}"}
            choice = json.loads(body)["choices"][0]
            reply = choice["message"].get("content") or ""
            if not isinstance(reply, str):
                raise TypeError("Expected text completion")
        except (subprocess.CalledProcessError, ValueError, TypeError, KeyError, IndexError, AttributeError):
            return {**result, "score": 0, "error": "Invalid or unavailable completion"}
        correct = (score_lot(reply, case) if evidence_eval
                   else score_route(reply, [], case["expected_cash"]))
        return {**result, "reply": reply, "finish_reason": choice.get("finish_reason"),
                "score": int(correct), "elapsed_seconds": round(time.perf_counter() - started, 3)}

    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(evaluate, cases))
    result = {"model": args.model, "correct": sum(row["score"] for row in replies),
              "total": len(replies), "max_tokens": args.max_tokens,
              "reasoning_effort": args.reasoning_effort, "replies": replies}
    result["failed_requests"] = sum("error" in row for row in replies)
    result["truncated"] = sum(row.get("finish_reason") == "length" for row in replies)
    if evidence_eval:
        totals = Counter(row["target"] for row in replies)
        correct_by_status = Counter(row["target"] for row in replies if row["score"])
        result["by_status"] = {label: {"correct": correct_by_status[label], "total": total}
                               for label, total in sorted(totals.items())}
    if args.expanded_evidence:
        totals = Counter(case["scenario"] for case in cases)
        correct = Counter(case["scenario"] for case, row in zip(cases, replies, strict=True) if row["score"])
        result["by_scenario"] = {name: {"correct": correct[name], "total": total}
                                 for name, total in sorted(totals.items())}
        result["status_correct"] = sum(
            lot_answer(row.get("reply", "")).get("status") == row["target"] for row in replies
        )
        result["false_supports"] = sum(
            row["target"] != "supported" and lot_answer(row.get("reply", "")).get("status") == "supported"
            for row in replies
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['correct']}/{result['total']}", flush=True)


if __name__ == "__main__":
    main()
