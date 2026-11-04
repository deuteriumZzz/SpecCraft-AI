"""Контракт LLM-клиента.

Сервисный слой знает только этот Protocol. Чтобы заменить Gemini на другого
провайдера или локальную модель (например, Ollama), достаточно написать один
новый класс с методом generate; сервисы, роутеры и тесты не меняются.
"""

from typing import Any, Protocol

from pydantic import BaseModel


class LLMClient(Protocol):
    def generate(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        """Возвращает JSON-объект ответа модели.

        Контракт ошибок: только типы из app.core.errors (LLMRateLimited, LLMTimeout,
        LLMUnavailable, LLMRequestRejected, InvalidModelOutput), без утечки деталей SDK.
        """
        ...
