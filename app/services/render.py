"""Форматы вывода для копирования: Markdown и обычный текст.

Менеджер копирует результат в CMS, где Markdown/HTML может рендериться. Поэтому каждое
динамическое значение (в том числе сырые данные поставщика из specs и названия)
обезвреживается здесь: начало тега заменяется на «‹», переводы строк схлопываются
(нельзя вставить «\\n# заголовок»), в Markdown экранируются скобки ссылок и бэктики.
"""

import re

from app.core.security import STRAY_LT
from app.schemas.card import CardOut


def _plain(text: str) -> str:
    return STRAY_LT.sub("‹", re.sub(r"\s+", " ", text)).strip()


def _md(text: str) -> str:
    text = _plain(text)
    for ch in ("[", "]", "`"):
        text = text.replace(ch, "\\" + ch)
    return text


def _cell(text: str) -> str:
    return _md(text).replace("|", "\\|")


def to_markdown(card: CardOut) -> str:
    lines = [f"# {_md(card.seo_title)}", "", _md(card.seo_description), "", "## Характеристики", ""]
    lines += ["| Параметр | Значение |", "| --- | --- |"]
    lines += [f"| {_cell(c.name)} | {_cell(c.value)} |" for c in card.characteristics]
    lines += ["", "## Поисковые запросы", ""] + [f"- {_md(q)}" for q in card.search_queries]
    lines += [
        "",
        "## Для менеджера",
        "",
        f"**Кому подходит:** {_md(card.commercial.audience)}",
        "",
        f"**Какие задачи решает:** {_md(card.commercial.tasks)}",
    ]
    if card.missing_fields:
        lines += ["", "## Не хватает данных", ""] + [f"- {_md(m)}" for m in card.missing_fields]
    if card.warnings:
        lines += ["", "## Предупреждения", ""] + [f"- {_md(w)}" for w in card.warnings]
    return "\n".join(lines) + "\n"


def to_text(card: CardOut) -> str:
    lines = [_plain(card.seo_title), "", _plain(card.seo_description), "", "Характеристики:"]
    lines += [f"- {_plain(c.name)}: {_plain(c.value)}" for c in card.characteristics]
    lines += ["", "Поисковые запросы: " + "; ".join(_plain(q) for q in card.search_queries), ""]
    lines += [
        f"Кому подходит: {_plain(card.commercial.audience)}",
        f"Какие задачи решает: {_plain(card.commercial.tasks)}",
    ]
    if card.missing_fields:
        lines += ["", "Не хватает данных: " + ", ".join(_plain(m) for m in card.missing_fields)]
    if card.warnings:
        lines += ["", "Предупреждения:"] + [f"- {_plain(w)}" for w in card.warnings]
    return "\n".join(lines) + "\n"
