"""Конфигурация приложения.

Все настройки берутся из переменных окружения / файла .env (он в .gitignore).
Валидация происходит при старте: если ключа или модели нет, приложение не
запустится, а не упадёт позже на первом запросе пользователя. Ключ хранится как
SecretStr, поэтому не попадает в repr, логи и трейсбеки.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["dev", "prod"] = "prod"
    # Длину проверяет get_settings: ошибка валидации pydantic печатает input_value,
    # то есть мог бы вывести неверный (но реальный) ключ в лог старта.
    gemini_api_key: SecretStr
    # Имя модели намеренно без значения по умолчанию: бесплатные модели и квоты
    # меняются, хардкод в коде быстро устареет.
    gemini_model: str = Field(min_length=1)
    llm_timeout_seconds: float = Field(default=30, gt=0, le=120)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    rate_limit: str = "10/minute"
    cors_origins: str = ""  # через запятую; пусто = CORS выключен

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"


@lru_cache
def get_settings() -> Settings:
    hint = "Скопируйте .env.example в .env и заполните (запускайте из корня проекта)."
    try:
        settings = Settings()  # type: ignore[call-arg]  # значения приходят из окружения
    except ValidationError as exc:
        # Только имена переменных: в сообщении pydantic есть input_value, то есть сам ключ.
        names = ", ".join(sorted({str(e["loc"][0]).upper() for e in exc.errors()}))
        message = f"Не заданы или некорректны переменные окружения: {names}. {hint}"
        raise SystemExit(message) from None
    if len(settings.gemini_api_key.get_secret_value()) < 10:
        raise SystemExit(f"GEMINI_API_KEY слишком короткий. {hint}")  # без значения ключа
    return settings
