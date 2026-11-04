"""JSON-логирование без чувствительных данных.

В лог пишутся только метаданные: id запроса, статус, длины, версия промпта,
латентность. Тела запросов, ответы модели, ключи и заголовки Authorization в
логи не попадают, поэтому логи безопасно отдавать в общую систему мониторинга.
"""

import json
import logging
import sys
from datetime import UTC, datetime

_logger = logging.getLogger("app")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    _logger.handlers = [handler]
    _logger.setLevel(logging.INFO)
    _logger.propagate = False
    # Библиотеки HTTP в INFO печатают URL запросов: глушим на всякий случай.
    for name in ("httpx", "httpcore", "google_genai", "google.genai"):
        logging.getLogger(name).setLevel(logging.WARNING)


def log_event(event: str, level: int = logging.INFO, **fields: object) -> None:
    _logger.log(level, event, extra={"fields": fields})
