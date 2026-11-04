"""Входной контракт: данные о товаре.

Валидация жёсткая и на границе доверия: лимиты длин, запрет лишних полей и
нестроковых значений, очистка управляющих символов. Всё, что прошло схему,
считается «чистым» и дальше по слоям уже не перепроверяется.
"""

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from app.core.security import clean_text

MAX_SPECS = 40
MAX_SPEC_KEY = 100
MAX_SPEC_VALUE = 300


class ProductIn(BaseModel):
    # extra="forbid": неизвестные поля не молча игнорируются, а дают 422.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "name": "Манометр технический МТ-100",
                "manufacturer": "Приборзавод Тест",
                "specs": {"диапазон измерений": "0–1,6 МПа", "класс точности": "1,5"},
                "description": "Прибор предназначен для измерения избыточного давления.",
            }
        },
    )

    name: StrictStr = Field(max_length=200)
    manufacturer: StrictStr = Field(default="", max_length=200)
    specs: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    description: StrictStr = Field(default="", max_length=8000)

    @field_validator("name", "manufacturer", "description")
    @classmethod
    def _clean(cls, value: str) -> str:
        return clean_text(value)

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        if not value:
            raise ValueError("название товара не может быть пустым")
        return value

    @field_validator("specs")
    @classmethod
    def _clean_specs(cls, specs: dict[str, str]) -> dict[str, str]:
        if len(specs) > MAX_SPECS:
            raise ValueError(f"слишком много характеристик (максимум {MAX_SPECS})")
        cleaned: dict[str, str] = {}
        for key, value in specs.items():
            key, value = clean_text(key), clean_text(value)
            if not key:
                raise ValueError("пустое название характеристики")
            if len(key) > MAX_SPEC_KEY:
                raise ValueError(f"название характеристики длиннее {MAX_SPEC_KEY} символов")
            if len(value) > MAX_SPEC_VALUE:
                raise ValueError(f"значение характеристики длиннее {MAX_SPEC_VALUE} символов")
            # Ключи, совпавшие после очистки (невидимые символы, регистр), раньше молча
            # склеивались и побеждала последняя: данные поставщика терялись без следа.
            if key.casefold() in {k.casefold() for k in cleaned}:
                raise ValueError(f"повторяющаяся характеристика: {key}")
            cleaned[key] = value
        return cleaned
