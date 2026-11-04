"""Выходные контракты: карточка товара, ошибка и схема ответа LLM.

LLMCard описывает только то, что просим у модели. Характеристики, список
недостающих полей и мета-данные собирает код, а не модель: это главная защита
от выдуманных характеристик.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

NO_DATA = "данных нет"


class Characteristic(BaseModel):
    name: str
    value: str


class Commercial(BaseModel):
    audience: str  # кому подходит прибор
    tasks: str  # какие задачи решает


class LLMSpec(BaseModel):
    name: str
    value: str


class LLMCard(BaseModel):
    """Схема структурированного ответа модели (без значений по умолчанию:
    так схему принимает Gemini response_schema)."""

    seo_title: str
    seo_description: str
    search_queries: list[str]
    commercial: Commercial
    extracted_specs: list[LLMSpec]
    warnings: list[str]


class CardMeta(BaseModel):
    prompt_version: str
    model: str


class CardOut(BaseModel):
    seo_title: str
    seo_description: str
    characteristics: list[Characteristic]
    search_queries: list[str]
    commercial: Commercial
    missing_fields: list[str]
    warnings: list[str]
    # Для каждого предупреждения (того же индекса): раздел карточки, к которому оно относится
    # («seo_title», «seo_description», «search_queries», «commercial», «characteristics»,
    # «input») или пустая строка. Интерфейс по нему подсвечивает нужное место.
    warning_fields: list[str]
    meta: CardMeta
    markdown: str
    text: str


class RenderIn(BaseModel):
    """Отредактированный менеджером черновик: из него заново собираются Markdown и текст.
    Лимиты ограничивают размер, чтобы эндпоинт нельзя было использовать для нагрузки."""

    model_config = ConfigDict(extra="forbid")

    seo_title: str = Field(max_length=300)
    seo_description: str = Field(max_length=5000)
    characteristics: list[Characteristic] = Field(max_length=100)
    search_queries: list[str] = Field(max_length=20)
    commercial: Commercial
    missing_fields: list[str] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _item_limits(self) -> "RenderIn":
        texts = [
            *self.search_queries, *self.missing_fields, *self.warnings,
            self.commercial.audience, self.commercial.tasks,
        ]
        if any(len(t) > 3000 for t in texts):
            raise ValueError("слишком длинный элемент списка")
        if any(len(c.name) > 200 or len(c.value) > 600 for c in self.characteristics):
            raise ValueError("слишком длинное название или значение характеристики")
        return self


class RenderOut(BaseModel):
    markdown: str
    text: str


class ErrorOut(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[str] = []
