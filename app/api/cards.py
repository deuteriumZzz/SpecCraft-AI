"""HTTP-слой: принять запрос, вызвать сервис, вернуть ответ. Без бизнес-логики."""

import threading

from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.deps import get_service
from app.core.config import get_settings
from app.core.errors import ServiceBusy
from app.schemas.card import CardOut, RenderIn, RenderOut
from app.schemas.product import ProductIn
from app.services.card_service import CardService

# Ограничение частоты защищает квоту Gemini от злоупотреблений.
# ponytail: счётчик в памяти процесса и ключ по IP клиента; для нескольких воркеров
# и reverse-proxy нужны Redis и доверенный X-Forwarded-For.
limiter = Limiter(key_func=get_remote_address)

# Одновременных генераций не больше MAX_CONCURRENT: запрос держит поток до минуты, и при сбое
# Gemini без ограничения все ~40 потоков пула заняли бы зависшие запросы (а /healthz остался бы
# зелёным). Лишний запрос сразу получает 503 с Retry-After.
MAX_CONCURRENT = 8
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)

router = APIRouter(prefix="/api", tags=["cards"])


@router.post("/cards", response_model=CardOut)
@limiter.limit(lambda: get_settings().rate_limit)
def create_card(
    request: Request, product: ProductIn, service: CardService = Depends(get_service)
) -> CardOut:
    # Обычный `def`: вызов LLM блокирующий, FastAPI выполнит его в пуле потоков.
    if not _slots.acquire(blocking=False):
        raise ServiceBusy()
    try:
        return service.generate(product)
    finally:
        _slots.release()


@router.post("/render", response_model=RenderOut)
@limiter.limit("120/minute")
def render_card(
    request: Request, card: RenderIn, service: CardService = Depends(get_service)
) -> RenderOut:
    """Markdown и текст для отредактированного черновика. LLM не вызывается, поэтому
    отдельный (щедрый) лимит и без ограничителя одновременных генераций."""
    return service.render_edited(card)
