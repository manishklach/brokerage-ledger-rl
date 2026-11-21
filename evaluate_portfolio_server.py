"""Score an OpenAI-compatible GPU model on the portfolio routing holdout."""

import argparse
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from portfolio_training import routing_cases, score_route


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--startup-timeout", type=int, default=900)
    parser.add_argument("--max-tokens", type=int, default=80)
    parser.add_argument("--reasoning-effort", choices=["none", "low", "medium", "high"])
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
    cases = routing_cases("eval", 44)

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
        return {"reply": reply, "target": case["expected_cash"], "finish_reason": choice["finish_reason"],
                "score": int(score_route(reply, [], case["expected_cash"]))}

    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(evaluate, cases))
    result = {"model": args.model, "correct": sum(row["score"] for row in replies),
              "total": len(replies), "max_tokens": args.max_tokens,
              "reasoning_effort": args.reasoning_effort, "replies": replies}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['correct']}/{result['total']}", flush=True)


if __name__ == "__main__":
    main()
