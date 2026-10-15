"""Error messages sent to the browser: user-fixable problems pass through, internals do not."""

from app.utils.errors import client_error_message


def test_value_errors_are_shown():
    exc = ValueError("The selected document was not found or has not finished indexing.")
    assert client_error_message(exc, "generating the answer") == str(exc)


def test_rate_limits_get_a_retry_hint():
    exc = RuntimeError("Error code: 429 - {'error': {'message': 'Rate limit reached for model'}}")
    assert "rate limited" in client_error_message(exc, "generating the answer")


def test_internal_details_are_hidden():
    exc = ConnectionError("could not connect to postgresql://admin:hunter2@db.internal:5432/rag")
    message = client_error_message(exc, "generating the answer")
    assert message == "Something went wrong while generating the answer. Please try again."
    assert "hunter2" not in message
