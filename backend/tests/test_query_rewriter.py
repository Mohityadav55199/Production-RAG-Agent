"""Follow-up question condensing: uses the history, never breaks retrieval."""

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.services import query_rewriter
from app.services.query_rewriter import _clean, condense_question

HISTORY = [HumanMessage(content="Where is the backend hosted?"), AIMessage(content="On Render.")]


def _run(coro):
    return asyncio.run(coro)


class _FakeLLM:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.seen = reply, error, None

    async def ainvoke(self, messages):
        self.seen = messages
        if self.error:
            raise self.error
        return AIMessage(content=self.reply)


def test_without_history_the_question_is_untouched(monkeypatch):
    monkeypatch.setattr(query_rewriter, "get_rewrite_llm", lambda: pytest.fail("no model call expected"))
    assert _run(condense_question("What about the frontend?", [])) == "What about the frontend?"


def test_follow_up_is_rewritten_using_recent_history(monkeypatch):
    llm = _FakeLLM(reply="Where is the frontend hosted?")
    monkeypatch.setattr(query_rewriter, "get_rewrite_llm", lambda: llm)
    assert _run(condense_question("What about the frontend?", HISTORY)) == "Where is the frontend hosted?"
    prompt = llm.seen[1].content
    assert "Where is the backend hosted?" in prompt and "What about the frontend?" in prompt


@pytest.mark.parametrize("llm", [None, _FakeLLM(error=RuntimeError("429")), _FakeLLM(reply="  ")])
def test_failures_fall_back_to_the_original_question(monkeypatch, llm):
    monkeypatch.setattr(query_rewriter, "get_rewrite_llm", lambda: llm)
    assert _run(condense_question("What about the frontend?", HISTORY)) == "What about the frontend?"


def test_clean_strips_labels_quotes_and_extra_lines():
    assert _clean('Query: "Where is the frontend hosted?"\nbecause...', "x") == "Where is the frontend hosted?"
    assert _clean("y" * 1000, "original") == "original"
