"""Загрузка и рендер промпта из YAML.

Промпт лежит вне кода, чтобы промпт-инженеры правили его без пересборки.
Рендер: простая однопроходная подстановка {{имя}} из белого списка. Не Jinja2 и
не eval: шаблонизатор с логикой дал бы пользовательским данным путь к SSTI.
Пользовательские значения предварительно экранируются (escape_tags) и
кодируются как JSON-строки, поэтому не могут закрыть тег изоляции.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.security import escape_tags
from app.schemas.product import ProductIn

DEFAULT_PATH = Path(__file__).with_name("card_generator.yaml")
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_ALLOWED = {"name", "manufacturer", "specs", "description", "feedback", "issues"}
_REQUIRED = ("version", "system", "user_template", "feedback_template")
_REQUIRED_USER = {"name", "manufacturer", "specs", "description", "feedback"}


@dataclass(frozen=True)
class PromptTemplate:
    version: str
    system: str
    user_template: str
    feedback_template: str


def load_prompt(path: Path = DEFAULT_PATH) -> PromptTemplate:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))  # safe_load: без исполнения кода
    if not isinstance(data, dict):
        raise ValueError(f"промпт {path.name} должен быть YAML-словарём")
    for key in _REQUIRED:
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"в промпте {path.name} нет поля {key}")
    for key in ("user_template", "feedback_template"):
        unknown = set(_PLACEHOLDER.findall(data[key])) - _ALLOWED
        if unknown:
            raise ValueError(f"недопустимые подстановки в {key}: {sorted(unknown)}")
    # Без этих подстановок модель не увидит данных, а ретрай не получит причину замечания,
    # при этом всё «работало бы»: поэтому их наличие проверяется при загрузке.
    for key, needed in (
        ("user_template", _REQUIRED_USER),
        ("feedback_template", {"issues"}),
    ):
        missing = needed - set(_PLACEHOLDER.findall(data[key]))
        if missing:
            raise ValueError(f"в {key} нет обязательных подстановок: {sorted(missing)}")
    return PromptTemplate(**{k: data[k] for k in _REQUIRED})


def _fill(template: str, values: dict[str, str]) -> str:
    # Один проход: значения, содержащие «{{x}}», повторно не раскрываются.
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), ""), template)


def _encode(value: str) -> str:
    return json.dumps(escape_tags(value), ensure_ascii=False)


def render_user(
    template: PromptTemplate, product: ProductIn, issues: list[str] | None = None
) -> str:
    specs = {escape_tags(k): escape_tags(v) for k, v in product.specs.items()}
    feedback = ""
    if issues:
        bullets = "\n".join(f"- {i}" for i in issues)
        feedback = _fill(template.feedback_template, {"issues": bullets})
    return _fill(
        template.user_template,
        {
            "name": _encode(product.name),
            "manufacturer": _encode(product.manufacturer),
            "specs": json.dumps(specs, ensure_ascii=False),
            "description": _encode(product.description),
            "feedback": feedback,
        },
    )
