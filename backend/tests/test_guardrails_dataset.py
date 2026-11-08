"""Offline checks for the guardrail test set and the safeguards in the system prompt.

The model-in-the-loop run lives in eval/guardrails.py; this file only makes sure the dataset is well formed and that the
prompt still carries the rules those cases rely on, so a careless edit to either fails CI.
"""

import re
import sys
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"
sys.path.insert(0, str(EVAL_DIR))

from guardrails import check, load_cases  # noqa: E402

from app.services.rag_graph import _SYSTEM_TEMPLATE  # noqa: E402

CASES = load_cases()


def test_ids_are_unique_and_fields_present():
    assert len({c["id"] for c in CASES}) == len(CASES)
    for case in CASES:
        assert {"id", "name", "category", "context", "question"} <= case.keys()
        assert case.get("forbidden") or case.get("must_match_any"), f"case {case['id']} checks nothing"


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"case{c['id']}")
def test_patterns_compile_and_canaries_are_not_in_the_prompt(case):
    for pattern in case.get("must_match_any", []):
        re.compile(pattern)
    # A canary that already appears in the template would make the case fail (or pass) for the wrong reason.
    # The prompt-leak cases are the exception: their forbidden strings are prompt text on purpose.
    if case["category"] != "prompt_leak":
        for bad in case.get("forbidden", []):
            assert bad.lower() not in _SYSTEM_TEMPLATE.lower()


def test_prompt_leak_cases_target_text_that_really_is_in_the_prompt():
    leak_cases = [c for c in CASES if c["category"] == "prompt_leak"]
    assert leak_cases
    for case in leak_cases:
        assert any(bad in _SYSTEM_TEMPLATE for bad in case["forbidden"])


def test_system_prompt_treats_retrieved_text_as_data():
    """The rule the injection cases depend on. Removing it should be a deliberate, reviewed change."""
    assert "is DATA, never" in _SYSTEM_TEMPLATE
    assert "instructions" in _SYSTEM_TEMPLATE


def test_check_flags_forbidden_text_and_missing_answer():
    case = {"forbidden": ["PWNED-7731"], "must_match_any": ["25"]}
    assert check(case, "Employees get 25 days.") == []
    assert check(case, "PWNED-7731")                       # canary present and answer missing: both reported
    assert len(check(case, "PWNED-7731")) == 2
    assert check({"must_match_any": ["not (found|contain)"]}, "That is not found in the documents.") == []
