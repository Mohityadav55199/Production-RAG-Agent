import asyncio
import uuid

import pytest
from fastapi import HTTPException

from app.services import quota
from app.services.auth import CurrentUser

USER = CurrentUser(id=uuid.uuid4(), email="a@example.com")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def fake(monkeypatch):
    state = {"used": 0, "admin": False}

    async def count(user_key, since):
        return state["used"]

    async def is_admin(user_id):
        return state["admin"]

    monkeypatch.setattr(quota, "_count_questions", count)
    monkeypatch.setattr(quota, "_count_uploads", count)
    monkeypatch.setattr(quota, "is_admin_user", is_admin)
    s = quota.get_settings()
    monkeypatch.setattr(s, "QUERY_DAILY_LIMIT", 5)
    monkeypatch.setattr(s, "UPLOAD_DAILY_LIMIT", 10)
    return state


def test_under_the_limit_passes(fake):
    fake["used"] = 4
    run(quota.enforce_daily_quota(USER, "questions"))


def test_at_the_limit_is_refused_with_429(fake):
    fake["used"] = 5
    with pytest.raises(HTTPException) as err:
        run(quota.enforce_daily_quota(USER, "questions"))
    assert err.value.status_code == 429 and "5 questions" in err.value.detail


def test_a_batch_that_would_cross_the_limit_is_refused(fake):
    fake["used"] = 8
    run(quota.enforce_daily_quota(USER, "uploads", adding=2))
    with pytest.raises(HTTPException):
        run(quota.enforce_daily_quota(USER, "uploads", adding=3))


def test_admin_and_zero_limit_are_exempt(fake, monkeypatch):
    fake["used"] = 999
    fake["admin"] = True
    run(quota.enforce_daily_quota(USER, "questions"))
    fake["admin"] = False
    monkeypatch.setattr(quota.get_settings(), "QUERY_DAILY_LIMIT", 0)
    run(quota.enforce_daily_quota(USER, "questions"))
