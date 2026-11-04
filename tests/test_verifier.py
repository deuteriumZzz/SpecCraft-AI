from app.schemas.card import Commercial, LLMCard
from app.services import verifier


def _allowed(source: str) -> set[str]:
    return verifier.source_numbers(source)


def test_number_formats_are_equivalent():
    allowed = _allowed("диапазон 0–1,6 МПа, модель 02")
    assert verifier.unsupported_numbers("до 1.6 МПа, модель 2", allowed) == []


def test_invented_number_is_detected():
    allowed = _allowed("класс точности 1,5")
    assert verifier.unsupported_numbers("класс точности 0.1", allowed) == ["0.1"]


def test_drop_unsupported_sentences_keeps_clean_ones():
    allowed = _allowed("класс точности 1,5")
    text, dropped = verifier.drop_unsupported_sentences(
        "Класс точности 1,5. Гарантия 10 лет. Подходит для воды.", allowed
    )
    assert dropped == 1 and "10" not in text and "1,5" in text and "воды" in text


def _card(**kw) -> LLMCard:
    base = dict(
        seo_title="Заголовок",
        seo_description="а" * 900,
        search_queries=["первый", "второй", "третий"],
        commercial=Commercial(audience="Предположение: инженеры.", tasks="Контроль."),
        extracted_specs=[],
        warnings=[],
    )
    return LLMCard(**{**base, **kw})


def test_length_issues():
    assert verifier.verify(_card(), set()) == []
    issues = verifier.verify(
        _card(seo_title="я" * 71, seo_description="коротко", search_queries=["один"]), set()
    )
    assert len(issues) == 3


def test_verify_reports_unsupported_numbers_in_any_field():
    card = _card(commercial=Commercial(audience="Для 500 заводов", tasks="x"))
    issues = verifier.verify(card, set())
    assert any("500" in i for i in issues)


def test_number_words_must_come_from_source():
    allowed = _allowed("класс точности 1,5")
    assert verifier.unsupported_numbers("гарантия пять лет", allowed) == ["пять"]
    assert verifier.unsupported_numbers("пять бар", _allowed("пять бар")) == []


def test_unicode_digits_and_trailing_zeros_are_normalised():
    assert verifier.unsupported_numbers("расход １２ м²", _allowed("расход 12 м²")) == []
    assert verifier.unsupported_numbers("0.5 МПа", _allowed("0,50 МПа")) == []
    assert verifier.unsupported_numbers("10 °C", _allowed("10.0 °C")) == []


def test_declined_number_words_are_caught():
    bad = verifier.unsupported_numbers("до пятнадцати бар, двух каналов, трёх режимов", set())
    assert len(bad) == 3
    assert verifier.unsupported_numbers("пятиэтажный корпус", set()) == []  # часть слова не в счёт
