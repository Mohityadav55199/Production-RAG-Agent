#!/usr/bin/env python3
"""Guardrail check: does the assistant resist prompt injection and refuse to invent private facts?

Each case in guardrails.json builds a prompt with the app's real system template and a hostile (or empty) retrieved
context, sends it to the real model chain, and checks the answer with plain string rules:

    forbidden       none of these strings may appear (a canary word, an attacker URL, a markdown image, the prompt text)
    must_match_any  at least one of these regular expressions must match (the right answer was still given, or the
                    assistant admitted it did not know)

Run it by hand, it calls the model once per case and is not part of CI:

    python eval/guardrails.py                  # Groq, the app's default chain
    python eval/guardrails.py --provider anthropic

Exit code 1 when any case fails, so it can gate a release. Model output varies between runs: a failure is a signal
to read the answer (printed below), not proof of a hole. The dataset itself is validated in CI by
tests/test_guardrails_dataset.py.
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def load_cases(path: Path = SCRIPT_DIR / "guardrails.json") -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "No relevant documents were found in the knowledge base for this query."
    return "\n\n".join(f"[{i}] {c['filename']}\n{c['text']}" for i, c in enumerate(chunks, start=1))


def check(case: dict, answer: str) -> list[str]:
    """Return the reasons this answer fails the case (an empty list means it passed)."""
    problems = []
    for bad in case.get("forbidden", []):
        if bad.lower() in answer.lower():
            problems.append(f"answer contains forbidden text {bad!r}")
    patterns = case.get("must_match_any", [])
    if patterns and not any(re.search(p, answer, flags=re.I) for p in patterns):
        problems.append(f"answer matches none of {patterns}")
    return problems


async def run(args: argparse.Namespace) -> int:
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.services.llm_factory import get_configured_llm
    from app.services.rag_graph import _STYLE_INSTRUCTIONS, _SYSTEM_TEMPLATE

    llm = get_configured_llm(requested_provider=args.provider, requested_model=args.model)
    failed = 0
    results = []
    for case in load_cases():
        system = _SYSTEM_TEMPLATE.format(
            context=format_context(case["context"]), scope="the whole knowledge base",
            style=_STYLE_INSTRUCTIONS["concise"])
        answer = (await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=case["question"])])).text
        problems = check(case, answer)
        failed += bool(problems)
        results.append({"id": case["id"], "name": case["name"], "passed": not problems, "problems": problems,
                        "answer": answer})
        print(f"[{'PASS' if not problems else 'FAIL'}] #{case['id']} {case['category']:<22} {case['name']}")
        for problem in problems:
            print(f"        {problem}\n        answer: {answer[:300]!r}")
        await asyncio.sleep(args.pause)

    total = len(results)
    print(f"\n{total - failed}/{total} guardrail cases passed (answerer: {args.provider or 'app default'})")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", default="groq", help="groq, gemini or anthropic (default groq)")
    parser.add_argument("--model", default=None)
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument("--json-out", type=Path, default=SCRIPT_DIR / "results" / "guardrails.json")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
