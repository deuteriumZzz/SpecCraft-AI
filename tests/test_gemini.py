"""Адаптер Gemini без сети: SDK подменяется заглушкой, time.sleep перехватывается."""

from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from app.core.config import Settings
from app.core.errors import (
    InvalidModelOutput,
    LLMRateLimited,
    LLMRequestRejected,
    LLMTimeout,
    LLMUnavailable,
)
from app.llm import gemini
from app.llm.gemini import GeminiClient
from app.schemas.card import LLMCard

OK = '{"a": 1}'


def _client(script, monkeypatch, timeout=30):
    settings = Settings(
        gemini_api_key="x" * 12, gemini_model="m", llm_max_retries=2, llm_timeout_seconds=timeout
    )
    client = GeminiClient(settings)
    calls, sleeps = [], []

    def fake(model, contents, config):
        calls.append(1)
        item = script[min(len(calls) - 1, len(script) - 1)]
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item)

    client._client = SimpleNamespace(models=SimpleNamespace(generate_content=fake))
    monkeypatch.setattr(gemini.time, "sleep", lambda s: sleeps.append(s))
    return client, calls, sleeps


def _call(client):
    return client.generate("sys", "user", LLMCard)


def _api(cls, code):
    return cls(code, {"error": {"message": "key=SECRET-VALUE"}})


def test_success(monkeypatch):
    client, calls, _ = _client([OK], monkeypatch)
    assert _call(client) == {"a": 1} and len(calls) == 1


def test_rate_limit_retries_with_long_pause_then_succeeds(monkeypatch):
    client, calls, sleeps = _client([_api(errors.ClientError, 429), OK], monkeypatch)
    assert _call(client) == {"a": 1} and len(calls) == 2
    assert sleeps and sleeps[0] >= 5  # квота «в минуту»: короткая пауза бесполезна


def test_rate_limit_gives_up_after_max_retries(monkeypatch):
    client, calls, _ = _client([_api(errors.ClientError, 429)], monkeypatch)
    with pytest.raises(LLMRateLimited):
        _call(client)
    assert len(calls) == 3


def test_client_error_is_not_retried(monkeypatch):
    client, calls, _ = _client([_api(errors.ClientError, 400)], monkeypatch)
    with pytest.raises(LLMRequestRejected):
        _call(client)
    assert len(calls) == 1


def test_server_error_is_retried(monkeypatch):
    client, calls, _ = _client([_api(errors.ServerError, 503), OK], monkeypatch)
    assert _call(client) == {"a": 1} and len(calls) == 2


def test_timeout_and_network_errors_are_mapped(monkeypatch):
    client, _, _ = _client([httpx.ReadTimeout("t")], monkeypatch)
    with pytest.raises(LLMTimeout):
        _call(client)
    client, _, _ = _client([httpx.ConnectError("c")], monkeypatch)
    with pytest.raises(LLMUnavailable):
        _call(client)


def test_empty_or_broken_output_is_retried_once(monkeypatch):
    client, calls, _ = _client([None, OK], monkeypatch)
    assert _call(client) == {"a": 1} and len(calls) == 2
    client, calls, _ = _client(["not json"], monkeypatch)
    with pytest.raises(InvalidModelOutput):
        _call(client)
    assert len(calls) == 2


def test_sdk_error_text_never_leaks(monkeypatch):
    client, _, _ = _client([_api(errors.ClientError, 400)], monkeypatch)
    with pytest.raises(LLMRequestRejected) as info:
        _call(client)
    assert "SECRET-VALUE" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_total_budget_stops_retries(monkeypatch):
    # Бюджет = 2 × таймаут = 2 с, а пауза после 429 — 5 с: повтор не делается.
    client, calls, _ = _client([_api(errors.ClientError, 429)], monkeypatch, timeout=1)
    with pytest.raises(LLMRateLimited):
        _call(client)
    assert len(calls) == 1
