"""Адаптер Google Gemini (SDK google-genai).

Структурированный вывод через response_schema: модель обязана вернуть JSON по
схеме, а не «по просьбе в тексте». Ошибки SDK переводятся в наши типы с
безопасными сообщениями. Ретраи только на 429/5xx/сетевые сбои (повтор 4xx
бессмыслен и может сжечь квоту) и один раз на пустой/битый ответ. Все попытки
укладываются в общий бюджет времени, чтобы один запрос не держал поток минутами.
"""

import json
import logging
import time
import traceback
from typing import Any

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import (
    AppError,
    InvalidModelOutput,
    LLMRateLimited,
    LLMRequestRejected,
    LLMTimeout,
    LLMUnavailable,
)
from app.core.logging import log_event

# Низкая температура: нужна точность и воспроизводимость, а не креатив.
TEMPERATURE = 0.2
# Потолок ответа: защита от «бесконечной» генерации. С запасом на «мысли» моделей-рассуждателей.
MAX_OUTPUT_TOKENS = 4096


class GeminiClient:
    def __init__(self, settings: Settings):
        self._client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
        self._model = settings.gemini_model
        self._timeout_ms = int(settings.llm_timeout_seconds * 1000)
        self._max_retries = settings.llm_max_retries
        self._budget_s = settings.llm_timeout_seconds * 2  # общий бюджет на все попытки

    def generate(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
            response_schema=schema,
            http_options=types.HttpOptions(timeout=self._timeout_ms),
        )
        deadline = time.monotonic() + self._budget_s
        for attempt in range(self._max_retries + 1):
            started = time.monotonic()
            try:
                response = self._client.models.generate_content(
                    model=self._model, contents=user, config=config
                )
                data = self._parse(response)  # лог «ok» только после успешного разбора
                self._log(attempt, "ok", started)
                return data
            except Exception as exc:  # переводим любое падение SDK в наш тип
                app_exc = exc if isinstance(exc, AppError) else self._translate(exc)
                self._log(attempt, app_exc.code, started, type(exc).__name__)
                delay = self._delay(app_exc, attempt)
                no_time = time.monotonic() + delay >= deadline
                if not self._retryable(app_exc, attempt) or attempt == self._max_retries or no_time:
                    if isinstance(exc, AppError):
                        raise
                    raise app_exc from None  # исходное исключение наружу не отдаём
                time.sleep(delay)
        raise LLMUnavailable()  # недостижимо, но явно

    @staticmethod
    def _retryable(exc: AppError, attempt: int) -> bool:
        if isinstance(exc, InvalidModelOutput):
            return attempt == 0  # пустой/битый ответ повторяем один раз
        return exc.retryable

    @staticmethod
    def _delay(exc: AppError, attempt: int) -> float:
        # 429 — квота «в минуту»: короткая пауза бесполезна, ждём дольше.
        base = 5 if isinstance(exc, LLMRateLimited) else 1
        return min(base * 2**attempt, 20)

    def _log(self, attempt: int, status: str, started: float, exc_type: str = "") -> None:
        level = logging.INFO if status == "ok" else logging.WARNING
        log_event("llm_call", level=level, model=self._model, attempt=attempt, status=status,
                  exc_type=exc_type, ms=int((time.monotonic() - started) * 1000))

    @staticmethod
    def _parse(response: Any) -> dict[str, Any]:
        text = getattr(response, "text", None)  # None при блокировке safety / пустом ответе
        if not text:
            # Причина нужна оператору: блокировка safety и обрезка по токенам детерминированны,
            # повтор запроса им не поможет.
            candidate = (getattr(response, "candidates", None) or [None])[0]
            feedback = getattr(response, "prompt_feedback", None)
            log_event(
                "llm_empty", level=logging.WARNING,
                finish_reason=str(getattr(candidate, "finish_reason", None)),
                block_reason=str(getattr(feedback, "block_reason", None)),
            )
            raise InvalidModelOutput()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise InvalidModelOutput() from None
        if not isinstance(data, dict):
            raise InvalidModelOutput()
        return data

    @staticmethod
    def _translate(exc: Exception) -> AppError:
        if isinstance(exc, httpx.TimeoutException):
            return LLMTimeout()
        if isinstance(exc, httpx.HTTPError):
            return LLMUnavailable()
        if isinstance(exc, errors.APIError):
            code = exc.code or 0
            if code == 429:
                return LLMRateLimited()
            if code >= 500:
                return LLMUnavailable()
            return LLMRequestRejected()
        # Не сетевая и не API-ошибка (TypeError после смены SDK и т.п.): это баг, а не сбой
        # сервиса. Не повторяем и не маскируем под временную недоступность без следа в логе.
        log_event(
            "llm_unexpected_error", level=logging.ERROR, exc_type=type(exc).__name__,
            frames="".join(traceback.format_tb(exc.__traceback__))[-1000:],
        )
        unexpected = LLMUnavailable()
        unexpected.retryable = False
        return unexpected
