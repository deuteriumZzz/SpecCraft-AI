from app.schemas.card import CardMeta, CardOut, Characteristic, Commercial
from app.services.render import to_markdown, to_text


def _card(value: str) -> CardOut:
    return CardOut(
        seo_title="Заголовок",
        seo_description="Описание.",
        characteristics=[Characteristic(name="параметр", value=value)],
        search_queries=["запрос"],
        commercial=Commercial(audience="Для инженеров.", tasks="Контроль."),
        missing_fields=[],
        warnings=[],
        warning_fields=[],
        meta=CardMeta(prompt_version="1", model="m"),
        markdown="",
        text="",
    )


def test_markdown_neutralises_supplier_data():
    evil = "<img src=x onerror=alert(1)>\n# Заголовок [click](javascript:alert(1)) `cmd`"
    md = to_markdown(_card(evil))
    assert "<img" not in md
    assert "\n# Заголовок" not in md  # перевод строки не даёт вставить свой заголовок
    assert "[click](" not in md and "`cmd`" not in md


def test_text_neutralises_tags_but_keeps_comparisons():
    text = to_text(_card("<script>x</script> и t < 50, > 10"))
    assert "<script" not in text
    assert "t < 50, > 10" in text
