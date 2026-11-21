"""Shared Claude client. Returns None when no API key is configured (offline mode)."""

import anthropic

from ..config import get_settings

settings = get_settings()
_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic | None:
    global _client
    if not settings.anthropic_api_key:
        return None
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=60.0, max_retries=2)
    return _client
