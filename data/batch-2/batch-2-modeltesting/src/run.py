#!/usr/bin/env python3
"""Parallel OpenAI runner for First Proof model testing.

Reads problems from $INPUT_PATH (default /data/input/input.json), dispatches
them concurrently against the OpenAI API, and writes one .tex per problem to
$OUTPUT_DIR (default /data/output). I/O paths mirror the batch2_design
submitter contract so this container is drop-in compatible.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError

INPUT_PATH = Path(os.environ.get("INPUT_PATH", "/data/input/input.json"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/data/output"))
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-nano")
CONCURRENCY = int(os.environ.get("CONCURRENCY", "10"))
PER_CALL_TIMEOUT = float(os.environ.get("PER_CALL_TIMEOUT", "120"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))

SYSTEM_PROMPT = (
    "You are a mathematician. Provide a clear, concise proof for the given problem."
)

client = AsyncOpenAI(timeout=PER_CALL_TIMEOUT)


async def call_model(latex: str) -> str:
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": latex},
                ],
            )
            content = resp.choices[0].message.content
            if not content:
                raise ValueError("empty response")
            return content
        except (RateLimitError, APITimeoutError, APIError, ValueError) as e:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = 2 ** attempt
            print(f"    retry {attempt + 1}/{MAX_RETRIES} after {type(e).__name__}: {e}; waiting {wait}s", flush=True)
            await asyncio.sleep(wait)


def wrap(latex: str, answer: str) -> str:
    block = (
        "\n\\bigskip\n"
        "\\textbf{LLM Response:}\n\n"
        "\\begin{verbatim}\n"
        f"{answer}\n"
        "\\end{verbatim}\n"
    )
    if r"\end{document}" in latex:
        return latex.replace(r"\end{document}", block + r"\end{document}")
    return latex + "\n" + block


async def handle(problem: dict, sem: asyncio.Semaphore) -> tuple[str, bool, str]:
    pid = problem["id"]
    latex = problem["latex"]
    async with sem:
        t0 = time.monotonic()
        print(f"  {pid}: dispatching", flush=True)
        try:
            answer = await call_model(latex)
        except Exception as e:
            dt = time.monotonic() - t0
            print(f"  {pid}: FAILED after {dt:.1f}s: {type(e).__name__}: {e}", flush=True)
            return pid, False, str(e)
        dt = time.monotonic() - t0
        out_path = OUTPUT_DIR / f"{pid}.tex"
        out_path.write_text(wrap(latex, answer))
        print(f"  {pid}: ok ({len(answer)} chars, {dt:.1f}s) -> {out_path.name}", flush=True)
        return pid, True, ""


async def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        return 2

    data = json.loads(INPUT_PATH.read_text())
    problems = data["problems"]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(
        f"model={MODEL} concurrency={CONCURRENCY} problems={len(problems)} "
        f"input={INPUT_PATH} output={OUTPUT_DIR}",
        flush=True,
    )

    sem = asyncio.Semaphore(CONCURRENCY)
    t0 = time.monotonic()
    results = await asyncio.gather(*(handle(p, sem) for p in problems))
    dt = time.monotonic() - t0

    ok = sum(1 for _, success, _ in results if success)
    failed = [(pid, err) for pid, success, err in results if not success]

    summary = {
        "model": MODEL,
        "concurrency": CONCURRENCY,
        "total": len(problems),
        "succeeded": ok,
        "failed": [{"id": pid, "error": err} for pid, err in failed],
        "wall_seconds": round(dt, 2),
    }
    (OUTPUT_DIR / "run-summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nDone in {dt:.1f}s: {ok}/{len(problems)} succeeded", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
