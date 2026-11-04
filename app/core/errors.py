"""Типизированные ошибки приложения.

Каждая ошибка несёт безопасное сообщение для пользователя и HTTP-статус.
Внутренние детали (текст исключения SDK, трейсбек) наружу не отдаются, чтобы не
раскрывать структуру системы; в лог пишется только тип и код.
"""


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "Внутренняя ошибка сервиса."
    retryable = False
    retry_after: int | None = None  # секунды: уходит клиенту заголовком Retry-After

    def __init__(self, message: str | None = None):
        super().__init__(message or self.message)
        if message:
            self.message = message


class LLMRateLimited(AppError):
    status_code = 429
    code = "llm_rate_limited"
    message = "Лимит запросов к модели исчерпан. Повторите через минуту."
    retryable = True
    retry_after = 60


class ServiceBusy(AppError):
    """Все слоты генерации заняты: лучше быстрый отказ, чем очередь, съедающая все потоки."""

    status_code = 503
    code = "service_busy"
    message = "Сервис занят. Повторите через несколько секунд."
    retry_after = 5


class LLMTimeout(AppError):
    status_code = 504
    code = "llm_timeout"
    message = "Модель не ответила вовремя. Повторите запрос."
    retryable = True


class LLMUnavailable(AppError):
    status_code = 502
    code = "llm_unavailable"
    message = "Сервис модели временно недоступен. Повторите позже."
    retryable = True


class LLMRequestRejected(AppError):
    """4xx от провайдера (кроме 429): ретраить бессмысленно."""

    status_code = 502
    code = "llm_request_rejected"
    message = "Запрос к модели отклонён. Обратитесь к администратору сервиса."


class InvalidModelOutput(AppError):
    status_code = 502
    code = "invalid_model_output"
    message = "Модель вернула некорректный ответ. Повторите запрос."
