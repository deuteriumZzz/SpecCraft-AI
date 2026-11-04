"""Фейковый LLM для тестов и evals (без сети и без квоты).

Два режима:
- outputs=None: детерминированно «пишет» корректную карточку по данным из промпта;
- outputs=[...]: отдаёт заданные ответы по очереди (последний повторяется),
  исключения выбрасываются. Так в тестах моделируются ошибки API и «взломанная»
  модель, нарушающая правила.
"""

import json
import re
from typing import Any

from pydantic import BaseModel

_FILLER = [
    "Описание подготовлено на основе данных, переданных контент-менеджером.",
    "Перед публикацией карточку необходимо проверить и при необходимости уточнить "
    "технические параметры по документации производителя.",
    "Прибор относится к контрольно-измерительному оборудованию и применяется "
    "в системах контроля технологических параметров.",
    "Подробные условия эксплуатации и комплектация указываются в паспорте изделия.",
]


def _field(user: str, tag: str) -> Any:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", user, re.S)
    return json.loads(match.group(1).strip()) if match else ""


def default_card(user: str) -> dict[str, Any]:
    name = _field(user, "product_name")
    maker = _field(user, "manufacturer")
    specs = _field(user, "specs") or {}
    intro = f"{name} — прибор" + (f" производителя {maker}." if maker else ".")
    parts = [intro]
    for key, value in specs.items():
        if value and len(" ".join(parts)) < 700:
            parts.append(f"{key.capitalize()}: {value}.")
    i = 0
    while len(" ".join(parts)) < 900:
        parts.append(_FILLER[i % len(_FILLER)])
        i += 1
    text = " ".join(parts)
    if len(text) > 1150:
        text = text[:1150].rsplit(" ", 1)[0].rstrip(",;:") + "."
    short = name.lower()[:60]
    return {
        "seo_title": name[:70],
        "seo_description": text,
        "search_queries": [f"{short} характеристики", f"{short} купить", f"{short} назначение"],
        "commercial": {
            "audience": "Предположение: специалисты по закупке и обслуживанию измерительного "
            "оборудования.",
            "tasks": "Предположение: контроль параметров технологического процесса.",
        },
        "extracted_specs": [],
        "warnings": [],
    }


class FakeLLM:
    def __init__(self, outputs: list[dict[str, Any] | Exception] | None = None):
        self._outputs = list(outputs) if outputs is not None else None
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        self.calls.append((system, user))
        if self._outputs is None:
            return default_card(user)
        item = self._outputs[0] if len(self._outputs) == 1 else self._outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
