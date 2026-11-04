"""Сборка списка характеристик и недостающих полей: детерминированно, в коде.

Модель не формирует характеристики: их значения берутся из входных `specs` как
есть. Это исключает выдуманные значения по построению. Из `description` разрешено
подтянуть характеристику только если её значение дословно (как отдельный токен)
есть в доверенном тексте описания, а в названии нет посторонних чисел.
"""

import re

from app.core.security import clean_text, strip_unsafe, trusted_text
from app.schemas.card import NO_DATA, Characteristic, LLMSpec
from app.schemas.product import MAX_SPEC_KEY, MAX_SPEC_VALUE, ProductIn
from app.services import verifier

MAX_EXTRACTED_SPECS = 20

# Характеристики, которые ожидает контент-менеджер для КИП: если их нет во входе, в карточке
# явная пометка «данных нет». Кортеж — признаки в названии ключа. Признаки узкие:
# «предел допускаемой погрешности» — не диапазон измерений, «диаметр корпуса» — не тип корпуса.
EXPECTED: list[tuple[str, tuple[str, ...]]] = [
    ("диапазон измерений", ("диапазон", "предел измер")),
    ("класс точности", ("точност",)),
    ("питание", ("питан", "напряжен")),
    ("тип корпуса", ("тип корпуса", "исполнение корпуса")),
    ("интерфейсы", ("интерфейс", "протокол")),
    ("присоединение", ("присоедин", "резьб")),
]
# Значения-заглушки поставщиков: для менеджера это то же самое, что «данных нет».
PLACEHOLDERS = {
    "-", "—", "–", "нет", "н/д", "n/a", "не указано", "не указан", "отсутствует", "нет данных",
    "данных нет",
}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold().replace("ё", "е")).strip()


def _empty(value: str) -> bool:
    return not value or norm(value) in PLACEHOLDERS


def accept_extracted(
    product: ProductIn,
    extracted: list[LLMSpec],
    allowed: set[str],
    trusted_input: bool = True,
) -> tuple[list[Characteristic], int]:
    """Принимает извлечённые моделью характеристики. Возвращает (принятые, число отклонённых).

    Условия: значение дословно в доверенном описании как отдельный токен (а не кусок
    «1250»), в названии нет чисел вне входных данных, ключ не дублирует ключ из specs.
    trusted_input=False (найдена инъекция в данных) отключает извлечение целиком.
    """
    if not trusted_input:
        return [], len(extracted)
    known = {norm(k) for k in product.specs}
    description = norm(trusted_text(product.description))
    trusted = trusted_text(product.description)
    accepted: list[Characteristic] = []
    rejected = max(0, len(extracted) - MAX_EXTRACTED_SPECS)
    for spec in extracted[:MAX_EXTRACTED_SPECS]:
        name, value = clean_text(spec.name), clean_text(spec.value)
        ok = bool(name and value) and len(name) <= MAX_SPEC_KEY and len(value) <= MAX_SPEC_VALUE
        ok = ok and norm(name) not in known
        ok = ok and not verifier.unsupported_numbers(name, allowed)
        ok = ok and re.search(
            rf"(?<![\w.,]){re.escape(norm(value))}(?![\w]|[.,]\d)", description
        ) is not None
        ok = ok and not any(strip_unsafe(t, trusted)[1] for t in (name, value))
        if not ok:
            rejected += 1
            continue
        known.add(norm(name))
        accepted.append(Characteristic(name=f"{name} (из описания)", value=value))
    return accepted, rejected


def build(
    product: ProductIn, extracted: list[Characteristic]
) -> tuple[list[Characteristic], list[str]]:
    """Возвращает (характеристики, список недостающих полей)."""
    missing: list[str] = []
    if not product.manufacturer:
        missing.append("производитель")
    if not product.description:
        missing.append("описание")

    chars: list[Characteristic] = []
    for key, value in product.specs.items():
        if _empty(value):
            chars.append(Characteristic(name=key, value=NO_DATA))
            missing.append(f"уточнить значение: {key}")
        else:
            chars.append(Characteristic(name=key, value=value))
    chars.extend(extracted)

    # Пустые spec тоже считаются «присутствующими»: они уже помечены как «уточнить значение»,
    # дублировать их строкой «данных нет» не нужно.
    keys = [norm(c.name) for c in chars]
    for label, hints in EXPECTED:
        if not any(h in key for key in keys for h in hints):
            chars.append(Characteristic(name=label, value=NO_DATA))
            missing.append(label)
    return chars, missing
