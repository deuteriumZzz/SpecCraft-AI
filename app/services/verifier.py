"""Детерминированная проверка ответа модели.

Модель плохо считает символы и может «досочинить» числа, поэтому проверки делает
код: длины полей и каждое число в тексте должно присутствовать во входных данных.
"""

import re
import unicodedata

from app.core.security import split_sentences
from app.schemas.card import LLMCard

TITLE_MAX = 70
DESC_MIN, DESC_MAX = 800, 1200
QUERIES_MIN, QUERIES_MAX = 3, 5

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# Числа словами тоже считаются числами: «пять бар» не должно проходить мимо проверки.
# Формы по падежам (после замены «ё» на «е»): «пять», «пяти», «пятью»; для составных
# числительных и порядков — основы с любым окончанием. Это эвристика, а не полный
# морфологический разбор: «один/одна» не включены, слишком частые в обычном тексте.
_WORDS = re.compile(
    r"\b(?:дв(?:а|е|ух|ум|умя)|тр(?:и|ех|ем|емя)|четыр(?:е|ех|ем|ьмя)|пят(?:ь|и|ью)"
    r"|шест(?:ь|и|ью)|сем(?:ь|и|ью)|восем(?:ь|и|ью)|восьм(?:и|ью)|девят(?:ь|и|ью)"
    r"|десят(?:ь|и|ью)|сто"
    r"|(?:одиннадцат|двенадцат|тринадцат|четырнадцат|пятнадцат|шестнадцат|семнадцат"
    r"|восемнадцат|девятнадцат|двадцат|тридцат|сорок|пятидесят|пятьдесят|шестидесят"
    r"|шестьдесят|семидесят|семьдесят|восьмидесят|восемьдесят|девяност|двест|трист"
    r"|четырест|пятьсот|пятисот|тысяч|миллион|полтор)\w*)\b",
    re.IGNORECASE,
)


def _variants(token: str) -> set[str]:
    token = token.replace(",", ".")  # «1,6» и «1.6» — одно число
    variants = {token, token.lstrip("0") or "0"}  # «02» и «2» — одно число
    if "." in token:
        short = token.rstrip("0").rstrip(".")  # «0.50» и «0.5», «10.0» и «10»
        variants |= {short, short.lstrip("0") or "0"}
    return variants


def _tokens(text: str) -> tuple[list[str], list[str]]:
    # NFKC только для сравнения: «м²» → «м2», полноширинные цифры → обычные, «½» → «1⁄2».
    folded = unicodedata.normalize("NFKC", text).replace("ё", "е").replace("Ё", "Е")
    return _NUMBER.findall(folded), [w.casefold() for w in _WORDS.findall(folded)]


def source_numbers(source: str) -> set[str]:
    digits, words = _tokens(source)
    result: set[str] = {f"w:{w}" for w in words}
    for token in digits:
        result |= _variants(token)
    return result


def unsupported_numbers(text: str, allowed: set[str]) -> list[str]:
    digits, words = _tokens(text)
    bad = [t for t in digits if not _variants(t) & allowed]
    return bad + [w for w in words if f"w:{w}" not in allowed]


def drop_unsupported_sentences(text: str, allowed: set[str]) -> tuple[str, int]:
    """Выбрасывает предложения с числами, которых нет во входе. Возвращает (текст, сколько)."""
    kept = [s for s in split_sentences(text) if not unsupported_numbers(s, allowed)]
    return " ".join(kept), len(split_sentences(text)) - len(kept)


def length_issues(card: LLMCard) -> list[str]:
    issues = []
    if len(card.seo_title) > TITLE_MAX:
        issues.append(f"seo_title длиннее {TITLE_MAX} символов (сейчас {len(card.seo_title)})")
    if not DESC_MIN <= len(card.seo_description) <= DESC_MAX:
        issues.append(
            f"seo_description должно быть {DESC_MIN}–{DESC_MAX} символов "
            f"(сейчас {len(card.seo_description)})"
        )
    if not QUERIES_MIN <= len(card.search_queries) <= QUERIES_MAX:
        issues.append(
            f"search_queries должно быть {QUERIES_MIN}–{QUERIES_MAX} "
            f"(сейчас {len(card.search_queries)})"
        )
    return issues


def verify(card: LLMCard, allowed: set[str]) -> list[str]:
    issues = length_issues(card)
    texts = [
        card.seo_title,
        card.seo_description,
        card.commercial.audience,
        card.commercial.tasks,
        *card.search_queries,
    ]
    bad = sorted({n for t in texts for n in unsupported_numbers(t, allowed)})
    if bad:
        issues.append(
            "в тексте есть числа, которых нет во входных данных: " + ", ".join(bad[:8])
            + ". Используй только числа из данных"
        )
    return issues
