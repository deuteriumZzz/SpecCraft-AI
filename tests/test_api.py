import os

from app.core.config import get_settings
from app.core.errors import LLMRateLimited, LLMUnavailable
from app.llm.fake import FakeLLM

PAYLOAD = {
    "name": "Манометр технический МТ-100",
    "manufacturer": "Приборзавод Тест",
    "specs": {"диапазон измерений": "0–1,6 МПа"},
    "description": "Измерение избыточного давления.",
}


def test_generate_card(make_client):
    r = make_client(FakeLLM()).post("/api/cards", json=PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert {"seo_title", "characteristics", "missing_fields", "markdown", "text"} <= body.keys()
    assert r.headers["x-request-id"]


def test_invalid_json_gives_safe_422(make_client):
    r = make_client(FakeLLM()).post(
        "/api/cards", content="{bad", headers={"content-type": "application/json"}
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_json"


def test_validation_error_does_not_echo_input(make_client):
    r = make_client(FakeLLM()).post("/api/cards", json={"name": "", "secret_field": "SECRET-123"})
    assert r.status_code == 422 and "SECRET-123" not in r.text


def test_body_too_large(make_client):
    r = make_client(FakeLLM()).post("/api/cards", json={**PAYLOAD, "description": "я" * 60000})
    assert r.status_code == 413


def test_provider_errors_are_mapped_without_leaks(make_client):
    r = make_client(FakeLLM([LLMRateLimited()])).post("/api/cards", json=PAYLOAD)
    assert r.status_code == 429 and r.json()["code"] == "llm_rate_limited"
    r = make_client(FakeLLM([LLMUnavailable()])).post("/api/cards", json=PAYLOAD)
    assert r.status_code == 502


def test_unexpected_error_hides_internals(make_client):
    client = make_client(FakeLLM([RuntimeError("api_key=SECRET-TRACE")]))
    r = client.post("/api/cards", json=PAYLOAD)
    assert r.status_code == 500
    assert "SECRET-TRACE" not in r.text and "Traceback" not in r.text


def test_security_headers_and_hidden_docs_in_prod(make_client):
    client = make_client(FakeLLM(), app_env="prod")
    r = client.post("/api/cards", json=PAYLOAD)
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_frontend_is_served(make_client):
    r = make_client(FakeLLM()).get("/")
    assert r.status_code == 200 and "SpecCraft" in r.text


def test_rate_limit(make_client):
    from app.api.cards import limiter

    os.environ["RATE_LIMIT"] = "2/minute"
    get_settings.cache_clear()
    limiter.enabled = True
    limiter.reset()
    try:
        client = make_client(FakeLLM())
        codes = [client.post("/api/cards", json=PAYLOAD).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
    finally:
        os.environ.pop("RATE_LIMIT")
        get_settings.cache_clear()


def test_missing_content_length_gets_411_with_headers(make_client):
    r = make_client(FakeLLM()).post("/api/cards", content=iter([b"{}"]))  # chunked: без длины
    assert r.status_code == 411 and r.json()["code"] == "length_required"
    assert r.headers["x-request-id"] and "content-security-policy" in r.headers


def test_unknown_route_uses_error_contract(make_client):
    r = make_client(FakeLLM()).get("/api/unknown")
    assert r.status_code == 404 and r.json()["code"] == "http_404" and r.json()["request_id"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_unexpected_error_still_gets_security_headers_and_request_id(make_client):
    r = make_client(FakeLLM([RuntimeError("boom")])).post("/api/cards", json=PAYLOAD)
    assert r.status_code == 500 and r.json()["request_id"] == r.headers["x-request-id"]
    assert "content-security-policy" in r.headers


def test_hijacked_model_never_leaks_through_the_http_response(make_client, product, good_output):
    bad = {**good_output}
    bad["seo_description"] += " Подробнее http://evil.example.com. Класс точности 0.1."
    r = make_client(FakeLLM([bad])).post("/api/cards", json=product.model_dump())
    assert r.status_code == 200
    for leaked in ("evil", "0.1"):
        assert leaked not in r.text, leaked  # ни в карточке, ни в markdown, ни в text


def test_busy_service_answers_503_with_retry_after(make_client, monkeypatch):
    import threading

    from app.api import cards

    monkeypatch.setattr(cards, "_slots", threading.BoundedSemaphore(1))
    cards._slots.acquire()  # единственный слот занят
    r = make_client(FakeLLM()).post("/api/cards", json=PAYLOAD)
    assert r.status_code == 503 and r.json()["code"] == "service_busy"
    assert r.headers["retry-after"] == "5"


def test_provider_rate_limit_has_retry_after(make_client):
    r = make_client(FakeLLM([LLMRateLimited()])).post("/api/cards", json=PAYLOAD)
    assert r.status_code == 429 and r.headers["retry-after"] == "60"


def test_validation_details_are_in_russian(make_client):
    body = make_client(FakeLLM()).post(
        "/api/cards", json={"name": "Датчик", "specs": {"класс точности": 1.5}, "price": 1}
    ).json()
    text = " ".join(body["details"])
    assert "нужна строка" in text and "неизвестное поле" in text
    assert "Input should" not in text and "Value error" not in text
