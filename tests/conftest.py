import os

# Тесты не ходят в сеть и не требуют реального ключа; значения только для валидации Settings.
os.environ.setdefault("GEMINI_API_KEY", "test-key-0123456789")
os.environ.setdefault("GEMINI_MODEL", "test-model")
os.environ.setdefault("APP_ENV", "dev")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.cards import limiter  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.llm.fake import FakeLLM  # noqa: E402
from app.main import create_app  # noqa: E402
from app.prompts.loader import load_prompt, render_user  # noqa: E402
from app.schemas.card import LLMCard  # noqa: E402
from app.schemas.product import ProductIn  # noqa: E402
from app.services.card_service import CardService  # noqa: E402


@pytest.fixture(autouse=True)
def _limiter_off():
    limiter.enabled = False
    limiter.reset()
    yield
    limiter.enabled = True


@pytest.fixture
def prompt():
    return load_prompt()


@pytest.fixture
def product():
    return ProductIn(
        name="Манометр технический МТ-100",
        manufacturer="Приборзавод Тест",
        specs={"диапазон измерений": "0–1,6 МПа", "класс точности": "1,5", "присоединение": "G1/2"},
        description="Прибор предназначен для измерения избыточного давления.",
    )


@pytest.fixture
def good_output(prompt, product):
    """Корректный ответ модели (словарь) для `product`: база для сценариев с порчей."""
    return FakeLLM().generate("", render_user(prompt, product), LLMCard)


@pytest.fixture
def make_service(prompt):
    def factory(llm):
        return CardService(llm, prompt, "test-model")

    return factory


@pytest.fixture
def make_client():
    def factory(llm, **overrides):
        settings = Settings(gemini_api_key="x" * 12, gemini_model="test-model", **overrides)
        # raise_server_exceptions=False: проверяем именно HTTP-ответ на непредвиденную ошибку.
        return TestClient(create_app(llm=llm, settings=settings), raise_server_exceptions=False)

    return factory
