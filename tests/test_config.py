import pytest

from app.core.config import get_settings


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    # Каталог без .env и без переменных: проверяем именно старт «из коробки».
    monkeypatch.chdir(tmp_path)
    for name in ("GEMINI_API_KEY", "GEMINI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_missing_settings_give_readable_message_without_values(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "short")
    with pytest.raises(SystemExit) as info:
        get_settings.__wrapped__()
    text = str(info.value)
    assert "GEMINI_MODEL" in text and ".env.example" in text
    assert "short" not in text  # значение ключа не попадает в сообщение


def test_too_short_key_is_rejected_without_echo(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "abc")
    clean_env.setenv("GEMINI_MODEL", "m")
    with pytest.raises(SystemExit) as info:
        get_settings.__wrapped__()
    assert "abc" not in str(info.value)


def test_valid_settings(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "abcdefghij1234")
    clean_env.setenv("GEMINI_MODEL", "m")
    settings = get_settings.__wrapped__()
    assert settings.gemini_model == "m" and "abcdefghij" not in repr(settings)
