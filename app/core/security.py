"""Санитизация входа и выхода, защита от prompt injection.

Слои защиты (промпт сам по себе недостаточен):
1. clean_text: убирает управляющие, zero-width и bidi-символы из входа.
2. escape_tags: не даёт пользовательскому тексту закрыть XML-тег изоляции.
3. detect_injection: эвристика-сигнал для менеджера (не блокировка).
4. strip_unsafe: вычищает из ответа модели URL, e-mail, телефоны и HTML,
   которых не было во входных данных (рекламные ссылки, XSS).

Все регулярные выражения ограничены по длине повторов и по длине сканируемого
текста (MAX_SCAN), чтобы входные данные и ответ модели не могли вызвать
катастрофический перебор (ReDoS) и занять рабочий поток.
"""

import re
import unicodedata
from typing import Final

# NFC, а не NFKC: NFKC превращает «м³» в «м3» и портит технические единицы.
_UNICODE_FORM: Final = "NFC"
MAX_SCAN = 20_000  # символов: больше регулярки не просматривают


def clean_text(value: str) -> str:
    value = unicodedata.normalize(_UNICODE_FORM, value)
    # U+2028/2029 (разделители строк) и \r не Cc/Cf, но для JS и JSON это переводы строк.
    value = value.replace(" ", "\n").replace(" ", "\n").replace("\r", "\n")
    # Cc (управляющие) и Cf (zero-width, bidi, soft hyphen), кроме переводов строк.
    value = "".join(
        ch for ch in value if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf")
    )
    value = re.sub(r"[ \t ]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def escape_tags(value: str) -> str:
    """Заменяет угловые скобки на похожие символы: `</description>` не закроет тег."""
    return value.replace("<", "‹").replace(">", "›")


# Латиница и кириллица с одинаковым начертанием: атакующий пишет «игнoрируй» с латинской «o».
_LATIN = "aceopxykABCEHKMOPTX"
_CYRILLIC = "асеорхукАВСЕНКМОРТХ"
_LAT_TO_CYR = str.maketrans(_LATIN, _CYRILLIC)
_CYR_TO_LAT = str.maketrans(_CYRILLIC, _LATIN)

# Все повторы ограничены ({0,3}), группы не пересекаются: перебор линейный.
_INJECTION = re.compile(
    r"игнорир\w{0,6}\s+(?:\w{1,15}\s+){0,3}?(?:инструкц|указани|правил|промпт)"
    r"|забудь\s+(?:\w{1,15}\s+){0,2}?(?:инструкц|правил|указани|вс[её]\b|предыдущ|прошл)"
    r"|(?:не\s+следуй|не\s+выполняй)\s+(?:\w{1,15}\s+){0,2}?(?:инструкц|правил|указани)"
    r"|системн\w{1,6}\s+промпт|ты\s+теперь|с\s+этого\s+момента\s+ты"
    r"|ignore\s+(?:\w{1,15}\s+){0,3}?(?:instructions?|rules?|prompts?)"
    r"|disregard\s+(?:\w{1,15}\s+){0,3}?(?:instructions?|rules?|above|previous)"
    r"|forget\s+(?:\w{1,15}\s+){0,3}?(?:instructions?|rules?|everything|above|previous)"
    r"|system\s+prompt|you\s+are\s+now|jailbreak"
    r"|</?\s*(?:product_data|product_name|manufacturer|specs|description|system)\b",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[\W_]+")


def _scan_variants(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text)[:MAX_SCAN]  # NFKC только для поиска
    out = []
    for variant in (folded, folded.translate(_LAT_TO_CYR), folded.translate(_CYR_TO_LAT)):
        out += [variant, _PUNCT.sub(" ", variant)]  # вариант без пунктуации: «ignore-all-…»
    return out


def detect_injection(*texts: str) -> bool:
    """Проверяет каждое поле отдельно и все вместе: фраза может быть разбита между полями."""
    candidates = [*texts, " ".join(texts)]
    return any(_INJECTION.search(v) for t in candidates for v in _scan_variants(t))


def trusted_text(text: str) -> str:
    """Текст как источник фактов: пусто, если в нём найдена инъекция.

    Числа и ссылки из такого текста не считаются доверенными: иначе «…класс точности 0.1…»
    из самой инъекции прошёл бы проверку «число есть во входе». Выбрано консервативное
    правило «весь текст», а не «одно предложение»: разбивка на предложения ломается на
    сокращениях вроде «см. http://…», и атакующий мог бы спрятать ссылку во вторую половину.
    Менеджер при этом видит предупреждение и проверяет исходное описание вручную.
    """
    return "" if detect_injection(text) else text


def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text.strip()) if s]


_TLDS = "ru|рф|com|net|org|io|su|info|biz|shop|store|ua|kz|by"
_URL = re.compile(
    r"(?:https?://|www\.)[^\s)\]>»]{1,500}"
    rf"|\b(?:[a-zа-я0-9-]{{1,63}}\.){{1,4}}(?:{_TLDS})\b[^\s]{{0,200}}",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,4}")
# Телефон: «+» и код страны, затем 2–4 группы цифр с ОДНИМ разделителем (пробел или дефис),
# либо российский 8/+7. Дополнительно нужно не менее 10 цифр (MIN_PHONE_DIGITS): иначе
# вырезались бы диапазоны «+20 40 60 80 °C» и ряды «0.1 0.25 0.4 … МПа».
_PHONE = re.compile(
    r"(?<![\w.])(?:\+\d{1,3}[\s-]?\(?\d{2,4}\)?(?:[\s-]\d{2,4}){2,4}"
    r"|(?:\+7|8)[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2})(?!\d)"
)
MIN_PHONE_DIGITS = 10
_TAG = re.compile(r"</?[A-Za-z!][^<>]{0,300}>")  # «t < 50 ... > 10» тегом не считается
STRAY_LT = re.compile(r"<(?=[A-Za-z/!?])")  # начало тега без закрытия: «<b», «</x»
_MD_LINK = re.compile(r"\[([^\]]{0,200})\]\(([^)]{0,500})\)")


def _in_source(fragment: str, source_l: str) -> bool:
    """Фрагмент есть в источнике как отдельный токен, а не как кусок более длинного.

    Простая подстрока считала бы «ya.ru» присутствующим в «maya.ru».
    """
    pattern = rf"(?<![\w.@-]){re.escape(fragment.casefold())}(?![\w-])"
    return re.search(pattern, source_l) is not None


def strip_unsafe(text: str, source: str) -> tuple[str, list[str]]:
    """Убирает из текста модели ссылки, почту, телефоны и HTML, которых нет в `source`.

    Возвращает очищенный текст и список типов удалённого (для warnings).
    """
    removed: list[str] = []
    if len(text) > MAX_SCAN:  # обрезка не должна быть незаметной
        text = text[:MAX_SCAN]
        removed.append("слишком длинный текст обрезан")
    source_l = source.casefold()

    def drop(kind: str, pattern: re.Pattern[str], current: str, min_digits: int = 0) -> str:
        def repl(m: re.Match[str]) -> str:
            frag = m.group(0)
            core = frag.rstrip(".,;:!?)»")  # знаки конца предложения не часть адреса
            if min_digits and sum(c.isdigit() for c in core) < min_digits:
                return frag  # мало цифр: это не телефон
            if _in_source(core, source_l):
                return frag
            if kind not in removed:
                removed.append(kind)
            return frag[len(core):]

        return pattern.sub(repl, current)

    def unlink(m: re.Match[str]) -> str:
        if not _in_source(m.group(2).strip(), source_l) and "ссылки" not in removed:
            removed.append("ссылки")
        return m.group(1)  # остаётся только текст ссылки

    if _TAG.search(text):
        removed.append("HTML")
        text = _TAG.sub(" ", text)
    if STRAY_LT.search(text):  # незакрытый «<b»: обезвреживаем, не удаляя текст вокруг
        if "HTML" not in removed:
            removed.append("HTML")
        text = STRAY_LT.sub("‹", text)
    text = _MD_LINK.sub(unlink, text)
    text = drop("e-mail", _EMAIL, text)  # до URL: иначе «b.com» из «a@b.com» примется за сайт
    text = drop("ссылки", _URL, text)
    text = drop("телефоны", _PHONE, text, min_digits=MIN_PHONE_DIGITS)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text.strip(), removed
