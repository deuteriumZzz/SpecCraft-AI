import pytest
from pydantic import ValidationError

from app.schemas.product import ProductIn


def test_valid_product_and_defaults():
    p = ProductIn(name="  Датчик  ")
    assert p.name == "Датчик" and p.manufacturer == "" and p.specs == {} and p.description == ""


def test_empty_name_rejected():
    with pytest.raises(ValidationError):
        ProductIn(name="   ")


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        ProductIn(name="Датчик", price=100)


def test_non_string_spec_values_rejected():
    with pytest.raises(ValidationError):
        ProductIn(name="Датчик", specs={"класс точности": 1.5})
    with pytest.raises(ValidationError):
        ProductIn(name="Датчик", specs={"интерфейсы": ["RS-485"]})


def test_limits():
    with pytest.raises(ValidationError):
        ProductIn(name="x" * 201)
    with pytest.raises(ValidationError):
        ProductIn(name="Датчик", description="x" * 8001)
    with pytest.raises(ValidationError):
        ProductIn(name="Датчик", specs={f"k{i}": "v" for i in range(41)})
    with pytest.raises(ValidationError):
        ProductIn(name="Датчик", specs={"k": "v" * 301})


def test_control_chars_are_cleaned_in_all_fields():
    p = ProductIn(name="Дат​чик", specs={"к\x00люч": "зна‮чение"}, description="а‏б")
    assert p.name == "Датчик" and p.specs == {"ключ": "значение"} and p.description == "аб"


def test_duplicate_spec_keys_after_cleaning_are_rejected():
    with pytest.raises(ValidationError, match="повторяющаяся"):
        ProductIn(name="Датчик", specs={"Давление": "1 МПа", "давление​": "9 МПа"})
