"""Зависимости FastAPI: роутеры получают сервис через DI, а не создают его сами."""

from fastapi import Request

from app.services.card_service import CardService


def get_service(request: Request) -> CardService:
    return request.app.state.service
