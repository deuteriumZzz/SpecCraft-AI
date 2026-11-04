"""Выходные контракты: карточка товара, ошибка и схема ответа LLM.

LLMCard описывает только то, что просим у модели. Характеристики, список
недостающих полей и мета-данные собирает код, а не модель: это главная защита
от выдуманных характеристик.
"""

from pydantic import BaseModel

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
    meta: CardMeta
    markdown: str
    text: str


class ErrorOut(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[str] = []
