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

# Нечисловые выдумки, которые модель добавляет чаще всего: отрасли применения, материалы,
# стандарты и сертификаты, гарантии. Если основа слова есть в тексте карточки, но её нет во
# входных данных, предложение считается непроверяемым. Это словарь, а не понимание смысла:
# он закрывает типичные случаи, но не все. Совпадение ищется по началу слова (после «ё»→«е»).
_CLAIMS = re.compile(
    r"(?<![\wа-я])(?:промышленн|энергетик|нефт|химическ|пищев|фармацевт|медицинск|жилищн"
    r"|коммунальн|жкх|теплоснабжен|водоснабжен|котельн|судостроен|авиацион|автомобильн"
    r"|металлург|горнодобыва|сельскохозяйствен|лабораторн|гост|iso\b|iec\b|сертифик"
    r"|поверк|гаранти|взрывозащищ|нержавеющ|латун|алюмини|стальн|сталь|пластик|бронз"
    r"|титан|керамик)",
    re.IGNORECASE,
)


def _variants(token: str) -> set[str]:
    token = token.replace(",", ".")  # «1,6» и «1.6» — одно число
    variants = {token, token.lstrip("0") or "0"}  # «02» и «2» — одно число
    if "." in token:
        short = token.rstrip("0").rstrip(".")  # «0.50» и «0.5», «10.0» и «10»
        variants |= {short, short.lstrip("0") or "0"}
    return variants


def _tokens(text: str) -> tuple[list[str], list[str], list[str]]:
    # NFKC только для сравнения: «м²» → «м2», полноширинные цифры → обычные, «½» → «1⁄2».
    folded = unicodedata.normalize("NFKC", text).replace("ё", "е").replace("Ё", "Е")
    return (
        _NUMBER.findall(folded),
        [w.casefold() for w in _WORDS.findall(folded)],
        [c.casefold() for c in _CLAIMS.findall(folded)],
    )


def source_numbers(source: str) -> set[str]:
    """Допустимые значения из входа: числа, числа словами («w:») и утверждения («c:»)."""
    digits, words, claims = _tokens(source)
    result: set[str] = {f"w:{w}" for w in words} | {f"c:{c}" for c in claims}
    for token in digits:
        result |= _variants(token)
    return result


def unsupported_numbers(text: str, allowed: set[str], claims: bool = True) -> list[str]:
    """Числа, числа словами и (при claims=True) рискованные утверждения без опоры во входе.
    В commercial-блоке и предупреждениях claims=False: там допустимы осторожные предположения."""
    digits, words, found = _tokens(text)
    bad = [t for t in digits if not _variants(t) & allowed]
    bad += [w for w in words if f"w:{w}" not in allowed]
    if claims:
        bad += [f"«{c}…»" for c in found if f"c:{c}" not in allowed]
    return bad


def drop_unsupported_sentences(
    text: str, allowed: set[str], claims: bool = True
) -> tuple[str, int]:
    """Выбрасывает предложения с непроверяемыми числами и утверждениями (текст, сколько)."""
    sentences = split_sentences(text)
    kept = [s for s in sentences if not unsupported_numbers(s, allowed, claims)]
    return " ".join(kept), len(sentences) - len(kept)


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
    strict = [card.seo_title, card.seo_description]
    # Допустимы предположения (commercial) и то, что вводит покупатель («манометр гост»).
    soft = [card.commercial.audience, card.commercial.tasks, *card.search_queries]
    bad = {n for t in strict for n in unsupported_numbers(t, allowed)}
    bad |= {n for t in soft for n in unsupported_numbers(t, allowed, claims=False)}
    if bad:
        issues.append(
            "в тексте есть числа или утверждения (отрасли, материалы, стандарты, гарантии), "
            "которых нет во входных данных: " + ", ".join(sorted(bad)[:8])
            + ". Используй только то, что есть в данных"
        )
    return issues
