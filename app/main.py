"""Сборка приложения: конфигурация, middleware, обработчики ошибок, статика.

Запуск: uvicorn app.main:create_app --factory --host 127.0.0.1
"""

import logging
import re
import time
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.cards import limiter, router
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import log_event, setup_logging
from app.llm.base import LLMClient
from app.llm.gemini import GeminiClient
from app.prompts.loader import load_prompt
from app.schemas.card import ErrorOut
from app.services.card_service import CardService

STATIC_DIR = Path(__file__).with_name("static")
MAX_BODY_BYTES = 64 * 1024
_LENGTH = re.compile(r"[0-9]{1,10}")  # только ASCII-цифры: isdigit() пропускает «²» и подобные
CSP = (
    "default-src 'self'; img-src 'self' data:; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
HTTP_MESSAGES = {404: "Ресурс не найден.", 405: "Метод не поддерживается."}


def _error(
    request: Request,
    status: int,
    code: str,
    message: str,
    details: list[str] | None = None,
    retry_after: int | None = None,
) -> JSONResponse:
    body = ErrorOut(
        code=code, message=message, details=details or [],
        request_id=getattr(request.state, "request_id", "-"),
    )
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    return JSONResponse(body.model_dump(), status_code=status, headers=headers)


def create_app(llm: LLMClient | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()  # падает при старте, если конфиг невалиден
    setup_logging()
    prompt = load_prompt()
    llm = llm or GeminiClient(settings)

    app = FastAPI(
        title="SpecCraft AI",
        # Swagger и схема только в dev: в prod они раскрывают структуру API.
        docs_url="/docs" if settings.is_dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.is_dev else None,
    )
    app.state.service = CardService(llm, prompt, settings.gemini_model)
    app.state.limiter = limiter

    def finish(request: Request, response: Response, started: float) -> Response:
        """Единый путь для ВСЕХ ответов (включая 411/413/500): заголовки, request id, лог."""
        dev_docs = settings.is_dev and request.url.path.startswith(("/docs", "/openapi"))
        headers = {"X-Content-Type-Options": "nosniff"} if dev_docs else SECURITY_HEADERS
        response.headers.update(headers)
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = request.state.request_id
        log_event(
            "request", method=request.method, path=request.url.path, status=response.status_code,
            ms=int((time.monotonic() - started) * 1000), request_id=request.state.request_id,
            client=request.client.host if request.client else "-",
        )
        return response

    @app.middleware("http")
    async def base_middleware(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex[:12]
        started = time.monotonic()
        if request.method == "POST":
            length = request.headers.get("content-length", "")
            if not _LENGTH.fullmatch(length):
                resp = _error(request, 411, "length_required", "Укажите Content-Length.")
                return finish(request, resp, started)
            if int(length) > MAX_BODY_BYTES:
                resp = _error(request, 413, "payload_too_large", "Слишком большой запрос.")
                return finish(request, resp, started)
        try:
            response = await call_next(request)
        except Exception as exc:
            # В лог: тип и кадры стека (без текста исключения: в нём могут быть детали SDK).
            log_event(
                "unhandled_error", level=logging.ERROR, exc_type=type(exc).__name__,
                request_id=request.state.request_id,
                frames="".join(traceback.format_tb(exc.__traceback__))[-1500:],
            )
            response = _error(request, 500, "internal_error", "Внутренняя ошибка сервиса.")
        return finish(request, response, started)

    # CORS добавляется ПОСЛЕ своего middleware, значит он внешний: заголовки CORS
    # получают и ответы 411/413/500, иначе браузер увидел бы лишь «сетевую ошибку».
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware, allow_origins=settings.cors_origin_list,
            allow_methods=["POST", "GET"], allow_headers=["Content-Type"],
        )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        # Код ошибки в лог: иначе в журнале запросов виден только статус (502 и т.п.).
        log_event(
            "app_error", level=logging.WARNING, code=exc.code, status=exc.status_code,
            request_id=request.state.request_id,
        )
        return _error(
            request, exc.status_code, exc.code, exc.message, retry_after=exc.retry_after
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return _error(
            request, 429, "rate_limited", "Слишком много запросов. Повторите позже.",
            retry_after=60,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        message = HTTP_MESSAGES.get(exc.status_code, "Ошибка запроса.")
        return _error(request, exc.status_code, f"http_{exc.status_code}", message)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        # Детали без поля input: не возвращаем клиенту его же данные и не раздуваем ответ.
        details = [
            f"{'.'.join(str(p) for p in e['loc'] if p != 'body') or 'тело запроса'}: {e['msg']}"
            for e in errors[:10]
        ]
        if any(e["type"] == "json_invalid" for e in errors):
            return _error(request, 422, "invalid_json", "Тело запроса не является корректным JSON.")
        return _error(request, 422, "invalid_input", "Некорректные входные данные.", details)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
