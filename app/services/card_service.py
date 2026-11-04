"""Бизнес-логика: оркестрация генерации карточки.

Конвейер: проверка входа на инъекции → промпт → LLM → схема → санитизация →
верификация (с ограниченными ретраями) → финализация → сборка характеристик →
рендер. Хендлеры и клиенты не знают порядка шагов: он зафиксирован здесь.
Принцип: всё, что код меняет или выбрасывает в ответе модели, явно попадает в warnings,
причём с адресом раздела карточки (warning_fields), чтобы интерфейс мог на него указать.
"""

import re

from pydantic import ValidationError

from app.core.errors import InvalidModelOutput
from app.core.logging import log_event
from app.core.security import detect_injection, strip_unsafe, trusted_text
from app.llm.base import LLMClient
from app.prompts.loader import PromptTemplate, render_user
from app.schemas.card import (
    NO_DATA,
    CardMeta,
    CardOut,
    Commercial,
    LLMCard,
    RenderIn,
    RenderOut,
)
from app.schemas.product import ProductIn
from app.services import characteristics, render, verifier

INJECTION_WARNING = (
    "Во входных данных найдены фразы, похожие на инструкции для модели. "
    "Они проигнорированы; проверьте исходный текст."
)
MAX_MODEL_QUERIES = 10  # больше модель не должна присылать: лишнее отбрасывается с пометкой
MAX_MODEL_WARNINGS = 5
MAX_WARNING_LEN = 200

# Предупреждение: (текст, раздел карточки или "" если относится ко всему ответу).
Note = tuple[str, str]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-—") or text[:limit]


def _build_source(product: ProductIn) -> tuple[str, bool]:
    """Доверенный источник фактов: данные без фраз, похожих на инструкции для модели.

    Возвращает (источник, найдена ли инъекция). Название, производитель и каждая
    характеристика проверяются отдельно; описание считается недоверенным, если
    инъекция найдена в любом поле или разбита между полями (проверка по всем сразу).
    """
    fields = [product.name, product.manufacturer, *product.specs, *product.specs.values()]
    flagged = detect_injection(*fields, product.description)
    specs = [f"{k}: {v}" for k, v in product.specs.items() if not detect_injection(k, v)]
    description = "" if flagged else product.description
    source = "\n".join(
        [trusted_text(product.name), trusted_text(product.manufacturer), *specs, description]
    )
    return source, flagged


class CardService:
    def __init__(
        self, llm: LLMClient, prompt: PromptTemplate, model_name: str, max_attempts: int = 2
    ):
        self._llm = llm
        self._prompt = prompt
        self._model = model_name
        self._max_attempts = max_attempts

    @staticmethod
    def render_edited(card: RenderIn) -> RenderOut:
        """Markdown и текст для отредактированного вручную черновика (без обращения к LLM)."""
        return RenderOut(markdown=render.to_markdown(card), text=render.to_text(card))

    def generate(self, product: ProductIn) -> CardOut:
        notes: list[Note] = []
        source, flagged = _build_source(product)
        allowed = verifier.source_numbers(source)
        if flagged:
            notes.append((INJECTION_WARNING, "input"))

        card, removed = self._ask_model(product, source, allowed)
        if removed:
            notes.append(("Из ответа модели удалено: " + ", ".join(sorted(removed)) + ".", ""))

        card, finalize_notes = self._finalize(card, product, allowed)
        notes += finalize_notes

        extracted, rejected = characteristics.accept_extracted(
            product, card.extracted_specs, allowed, not flagged
        )
        if rejected:
            notes.append((
                f"Отклонено характеристик, извлечённых моделью из описания: {rejected} "
                "(значение не найдено в тексте или в названии есть лишние числа).",
                "characteristics",
            ))
        chars, missing = characteristics.build(product, extracted)

        out = CardOut(
            seo_title=card.seo_title,
            seo_description=card.seo_description,
            characteristics=chars,
            search_queries=card.search_queries,
            commercial=card.commercial,
            missing_fields=missing,
            warnings=[text for text, _ in notes],
            warning_fields=[field for _, field in notes],
            meta=CardMeta(prompt_version=self._prompt.version, model=self._model),
            markdown="",
            text="",
        )
        out.markdown, out.text = render.to_markdown(out), render.to_text(out)
        log_event(
            "card_generated",
            prompt_version=self._prompt.version,
            desc_len=len(out.seo_description),
            warnings=len(notes),
            missing=len(missing),
        )
        return out

    def _ask_model(
        self, product: ProductIn, source: str, allowed: set[str]
    ) -> tuple[LLMCard, set[str]]:
        """Запрос к модели с ограниченным числом повторов при нарушении проверок."""
        issues: list[str] | None = None
        last: tuple[LLMCard, set[str]] | None = None
        for _ in range(self._max_attempts):
            user = render_user(self._prompt, product, issues)
            raw = self._llm.generate(self._prompt.system, user, LLMCard)
            try:
                card = LLMCard.model_validate(raw)
            except ValidationError as exc:
                # Только число и пути полей, без значений: в ответе модели может быть что угодно.
                log_event(
                    "schema_invalid",
                    level=30,
                    error_count=exc.error_count(),
                    fields=[".".join(str(p) for p in e["loc"]) for e in exc.errors()[:10]],
                )
                issues = ["ответ не соответствует схеме JSON"]
                continue
            card, removed = self._sanitize(card, source)
            last = (card, removed)
            issues = verifier.verify(card, allowed)
            if not issues:
                break
        if last is None:
            raise InvalidModelOutput()
        return last

    @staticmethod
    def _sanitize(card: LLMCard, source: str) -> tuple[LLMCard, set[str]]:
        removed: set[str] = set()

        def clean(text: str) -> str:
            cleaned, kinds = strip_unsafe(text, source)
            removed.update(kinds)
            return cleaned

        data = card.model_copy(deep=True)
        # Размер ответа модели ограничиваем до разбора: схема лимитов не задаёт.
        if (
            len(data.search_queries) > MAX_MODEL_QUERIES
            or len(data.extracted_specs) > characteristics.MAX_EXTRACTED_SPECS
            or len(data.warnings) > MAX_MODEL_WARNINGS
        ):
            removed.add("лишние элементы списков")
        data.search_queries = data.search_queries[:MAX_MODEL_QUERIES]
        data.extracted_specs = data.extracted_specs[: characteristics.MAX_EXTRACTED_SPECS]
        data.warnings = data.warnings[:MAX_MODEL_WARNINGS]
        data.seo_title = clean(data.seo_title)
        data.seo_description = clean(data.seo_description)
        data.search_queries = [clean(q) for q in data.search_queries]
        data.commercial = Commercial(
            audience=clean(data.commercial.audience), tasks=clean(data.commercial.tasks)
        )
        data.warnings = [clean(w) for w in data.warnings]
        for spec in data.extracted_specs:
            spec.name, spec.value = clean(spec.name), clean(spec.value)
        return data, removed

    @staticmethod
    def _finalize(
        card: LLMCard, product: ProductIn, allowed: set[str]
    ) -> tuple[LLMCard, list[Note]]:
        """Последняя линия обороны: то, что не удалось исправить ретраями, чистится кодом
        и явно помечается в warnings (молча ничего не правим). Не меняет переданный объект."""
        card = card.model_copy(deep=True)
        notes: list[Note] = []

        title = card.seo_title
        if not title:
            title = _truncate(product.name, verifier.TITLE_MAX)
            notes.append(
                ("Модель вернула пустой заголовок: подставлено название товара.", "seo_title")
            )
        elif verifier.unsupported_numbers(title, allowed):
            title = _truncate(product.name, verifier.TITLE_MAX)
            notes.append((
                "Заголовок заменён на название товара: модель добавила лишние числа.",
                "seo_title",
            ))
        if len(title) > verifier.TITLE_MAX:
            title = _truncate(title, verifier.TITLE_MAX)
            notes.append((f"Заголовок обрезан до {verifier.TITLE_MAX} символов.", "seo_title"))
        card.seo_title = title

        desc, dropped = verifier.drop_unsupported_sentences(card.seo_description, allowed)
        if dropped:
            notes.append((
                f"Удалено предложений с непроверяемыми числами в описании: {dropped}.",
                "seo_description",
            ))
        card.seo_description = desc
        if not verifier.DESC_MIN <= len(desc) <= verifier.DESC_MAX:
            notes.append((
                f"Длина SEO-описания {len(desc)} символов, норма {verifier.DESC_MIN}–"
                f"{verifier.DESC_MAX}: отредактируйте вручную.",
                "seo_description",
            ))

        audience, n_a = verifier.drop_unsupported_sentences(card.commercial.audience, allowed)
        tasks, n_t = verifier.drop_unsupported_sentences(card.commercial.tasks, allowed)
        if n_a or n_t:
            notes.append((
                "Из commercial-блока удалены предложения с непроверяемыми числами.", "commercial"
            ))
        card.commercial = Commercial(audience=audience or NO_DATA, tasks=tasks or NO_DATA)

        queries: list[str] = []
        dropped_queries = 0
        for q in card.search_queries:
            q = re.sub(r"\s+", " ", q).strip().lower()
            if not q or q in queries:
                continue
            if verifier.unsupported_numbers(q, allowed):
                dropped_queries += 1
                continue
            queries.append(q)
        if dropped_queries:
            notes.append((
                f"Удалено поисковых запросов с непроверяемыми числами: {dropped_queries}.",
                "search_queries",
            ))
        card.search_queries = queries[: verifier.QUERIES_MAX]
        if len(card.search_queries) < verifier.QUERIES_MIN:
            notes.append((
                f"Поисковых запросов меньше {verifier.QUERIES_MIN}: добавьте вручную.",
                "search_queries",
            ))

        # Предупреждения модели тоже её текст: числа без опоры во входе в них не допускаются.
        model_warnings: list[Note] = []
        for warning in card.warnings:
            text, _ = verifier.drop_unsupported_sentences(warning, allowed)
            if text.strip():
                model_warnings.append((f"Модель: {text.strip()[:MAX_WARNING_LEN]}", ""))
            elif warning.strip():
                notes.append(("Предупреждение модели удалено: в нём непроверяемые числа.", ""))
        card.warnings = [text for text, _ in model_warnings]
        return card, notes + model_warnings
