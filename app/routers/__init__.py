"""Роутеры приложения.

Все маршруты собраны здесь и подключаются в `app/main.py`. Роутеры используют
одни и те же модели из `app/schemas`, поэтому контракт для фронта один.
"""

from app.routers.admin import router as admin_router
from app.routers.admin import runs_router as admin_runs_router
from app.routers.auth import router as auth_router
from app.routers.clients import router as clients_router
from app.routers.events import router as events_router
from app.routers.insights import router as insights_router

__all__ = [
    "admin_router",
    "admin_runs_router",
    "auth_router",
    "clients_router",
    "events_router",
    "insights_router",
]
