import pytest
from pydantic import ValidationError

from app.api.feedback import FeedbackRequest


def test_valid_rating_is_accepted():
    body = FeedbackRequest(rating="down", question="q", answer="a", cited_files=["a.pdf"], comment="wrong page")
    assert body.rating == "down" and body.conversation_id is None


@pytest.mark.parametrize("bad", [
    {"rating": "meh", "question": "q", "answer": "a"},
    {"rating": "up", "question": "", "answer": "a"},
    {"rating": "up", "question": "q", "answer": "a", "cited_files": ["x"] * 21},
    {"rating": "up", "question": "q", "answer": "a", "comment": "c" * 1001},
])
def test_invalid_payloads_are_rejected(bad):
    with pytest.raises(ValidationError):
        FeedbackRequest(**bad)
