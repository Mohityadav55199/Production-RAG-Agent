"""What a failed request may tell the browser.

Services raise ``ValueError`` for problems the user can fix ("the selected document was not found"), so
those messages are shown as they are. Anything else can carry driver, provider or configuration details,
so the client gets a generic message and the full exception goes to the log.
"""

_RATE_LIMIT_HINTS = ("429", "rate limit", "rate_limit", "tokens per minute", "resource_exhausted", "quota")


def client_error_message(exc: BaseException, action: str) -> str:
    """A safe, user-facing message for *exc*; *action* completes "Something went wrong while ..."."""
    if isinstance(exc, ValueError):
        return str(exc)
    if any(hint in str(exc).lower() for hint in _RATE_LIMIT_HINTS):
        return "The AI provider is busy (rate limited). Please try again in a minute."
    return f"Something went wrong while {action}. Please try again."
