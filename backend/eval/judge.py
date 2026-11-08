#!/usr/bin/env python3
"""Answer-quality check: does the final answer stay faithful to the retrieved text and match the ground truth?

evaluate.py only measures retrieval (was the right passage found?). This script goes one step further. For each
question it retrieves chunks with the real pipeline, generates an answer with the app's own prompt, and asks a
*different* model (Gemini by default) to grade the answer. Grades are:

    faithful   every statement in the answer is supported by the retrieved context (yes / partial / no)
    correct    the answer agrees with the ground truth in dataset.json            (yes / partial / no)
    cites      the answer names an expected source file                           (plain string check, no LLM)

"yes" counts 1, "partial" 0.5, "no" 0. Run it by hand: it makes two model calls per question, so it is not part of CI.

    python eval/judge.py                          # 20 evenly spaced questions, Groq answers, Gemini judge
    python eval/judge.py --limit 60               # the whole dataset
    python eval/judge.py --provider anthropic     # grade the model the deployed app uses first (costs more)

Needs GOOGLE_API_KEY (embeddings and judge) and the key of the answering provider in backend/.env.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from evaluate import LiveBenchmarkIndex, load_dataset  # noqa: E402

GRADE = {"yes": 1.0, "partial": 0.5, "no": 0.0}

JUDGE_PROMPT = """You are grading an answer produced by a retrieval-augmented assistant. Be strict and literal.

QUESTION:
{question}

RETRIEVED CONTEXT (the only material the assistant was allowed to use):
{context}

ASSISTANT ANSWER:
{answer}

REFERENCE ANSWER (ground truth):
{truth}

Grade two things.
1. faithful: is every factual statement in the assistant answer supported by the retrieved context?
   "yes" = all supported; "partial" = mostly supported but at least one claim is not in the context; "no" = mostly unsupported.
2. correct: does the assistant answer agree with the reference answer on the facts the question asks for?
   "yes" = agrees; "partial" = right but incomplete or with a wrong detail; "no" = wrong or does not answer.

Reply with JSON only, no other text: {{"faithful": "yes|partial|no", "correct": "yes|partial|no", "reason": "<one sentence>"}}"""


def pick_evenly(items: list, limit: int) -> list:
    """Every k-th item, so a small sample still covers every question category."""
    if limit >= len(items):
        return items
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def parse_grade(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if data.get("faithful") not in GRADE or data.get("correct") not in GRADE:
        return None
    return data


def format_context(candidates) -> str:
    return "\n\n".join(f"[{i}] {c.filename}\n{c.text}" for i, c in enumerate(candidates, start=1))


async def run(args: argparse.Namespace) -> None:
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.services.llm_factory import get_configured_llm, get_vision_llm
    from app.services.rag_graph import _STYLE_INSTRUCTIONS, _SYSTEM_TEMPLATE

    dataset = pick_evenly(load_dataset(SCRIPT_DIR / "dataset.json"), args.limit)
    index = LiveBenchmarkIndex(SCRIPT_DIR / "corpus", condense=True, hybrid=True)
    answerer = get_configured_llm(requested_provider=args.provider, requested_model=args.model)
    judge = get_vision_llm(streaming=False)   # Gemini: a different model family from the answerer

    rows = []
    for n, item in enumerate(dataset, start=1):
        candidates = await index.search(item.question, top_k=5, min_score=0.63, max_gap=0.05, history=item.history)
        context = format_context(candidates) if candidates else "No relevant documents were found in the knowledge base."

        messages = [SystemMessage(content=_SYSTEM_TEMPLATE.format(
            context=context, scope="the whole knowledge base", style=_STYLE_INSTRUCTIONS["concise"]))]
        for turn in item.history:
            messages.append(HumanMessage(content=turn["content"]) if turn["role"] == "user" else _ai(turn["content"]))
        messages.append(HumanMessage(content=item.question))

        started = time.perf_counter()
        answer = (await answerer.ainvoke(messages)).text
        answer_ms = int((time.perf_counter() - started) * 1000)

        verdict = None
        for _ in range(2):   # one retry if the judge does not return valid JSON
            reply = await judge.ainvoke([HumanMessage(content=JUDGE_PROMPT.format(
                question=item.question, context=context, answer=answer, truth=item.ground_truth))])
            verdict = parse_grade(reply.text)
            if verdict:
                break
        cites = any(source.lower() in answer.lower() for source in item.expected_sources)

        rows.append({
            "id": item.id, "category": item.category, "question": item.question, "answer": answer,
            "faithful": (verdict or {}).get("faithful"), "correct": (verdict or {}).get("correct"),
            "reason": (verdict or {}).get("reason"), "cites_expected_source": cites, "answer_ms": answer_ms,
        })
        print(f"[{n}/{len(dataset)}] Q{item.id} {item.category:<20} faithful={rows[-1]['faithful']} "
              f"correct={rows[-1]['correct']} cites={cites}")
        await asyncio.sleep(args.pause)

    report(rows, args)


def _ai(text: str):
    from langchain_core.messages import AIMessage
    return AIMessage(content=text)


def report(rows: list[dict], args: argparse.Namespace) -> None:
    graded = [r for r in rows if r["faithful"] and r["correct"]]
    skipped = len(rows) - len(graded)

    def score(group: list[dict], key: str) -> float:
        return sum(GRADE[r[key]] for r in group) / len(group) if group else 0.0

    by_category: dict[str, list[dict]] = defaultdict(list)
    for r in graded:
        by_category[r["category"]].append(r)

    print("\n" + "=" * 70)
    print(f"Answer quality on {len(graded)} graded questions ({skipped} ungraded), answerer = "
          f"{args.provider or 'app default'}{':' + args.model if args.model else ''}")
    print(f"  Faithfulness : {score(graded, 'faithful') * 100:5.1f}%")
    print(f"  Correctness  : {score(graded, 'correct') * 100:5.1f}%")
    print(f"  Cites source : {sum(r['cites_expected_source'] for r in graded) / max(len(graded), 1) * 100:5.1f}%")
    print("-" * 70)
    for name, group in sorted(by_category.items()):
        print(f"  {name:<20} n={len(group):<3} faithful={score(group, 'faithful') * 100:5.1f}%  "
              f"correct={score(group, 'correct') * 100:5.1f}%")
    for r in graded:
        if r["faithful"] != "yes" or r["correct"] != "yes":
            print(f"\n  Q{r['id']} ({r['faithful']}/{r['correct']}): {r['question']}\n     {r['reason']}")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "answerer": f"{args.provider or 'default'}:{args.model or ''}", "judge": "gemini", "graded": len(graded),
            "faithfulness": round(score(graded, "faithful"), 4), "correctness": round(score(graded, "correct"), 4),
            "cites_expected_source": round(sum(r["cites_expected_source"] for r in graded) / max(len(graded), 1), 4),
        }
        args.json_out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
        print(f"\nSaved {args.json_out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=20, help="how many questions to grade (default 20)")
    parser.add_argument("--provider", default="groq", help="answering provider: groq, gemini or anthropic (default groq)")
    parser.add_argument("--model", default=None, help="answering model; default is the provider's configured model")
    parser.add_argument("--pause", type=float, default=1.0, help="seconds to wait between questions (rate limits)")
    parser.add_argument("--json-out", type=Path, default=SCRIPT_DIR / "results" / "judge.json")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
