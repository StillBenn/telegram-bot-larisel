"""Мидлвари: антиспам и регистрация пользователя.

Мидлварь выполняется до хендлера, поэтому здесь удобно решать задачи, которые
иначе пришлось бы копировать в каждый хендлер.
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from . import db, texts


class ThrottlingMiddleware(BaseMiddleware):
    """Не пропускает больше одного нажатия в `rate` секунд от одного пользователя.

    Защищает от «дребезга» инлайн-кнопок: пользователь бьёт по ➕ пять раз подряд,
    Telegram присылает пять апдейтов, и без этого бот пять раз перерисовывает
    корзину, обгоняя сам себя.

    ВАЖНО: вешается только на callback_query (см. bot.py). На сообщениях эта же
    логика молча съедала бы текст пользователя — потерять введённый телефон
    хуже, чем обработать два сообщения подряд.
    """

    def __init__(self, rate: float = 0.4, cleanup_after: int = 600) -> None:
        self._rate = rate
        self._cleanup_after = cleanup_after
        self._last: dict[int, float] = {}
        self._last_cleanup = time.monotonic()

    def _cleanup(self, now: float) -> None:
        """Иначе словарь растёт вместе с числом пользователей и не уменьшается."""
        if now - self._last_cleanup < self._cleanup_after:
            return
        self._last_cleanup = now
        stale = [uid for uid, ts in self._last.items() if now - ts > self._cleanup_after]
        for uid in stale:
            del self._last[uid]

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        now = time.monotonic()
        self._cleanup(now)
        previous = self._last.get(user.id, 0.0)
        if now - previous < self._rate:
            # Callback гасим тихо: всплывающее окно на каждый быстрый тап
            # раздражает сильнее, чем сама задержка.
            if isinstance(event, CallbackQuery):
                await event.answer()
            return None
        self._last[user.id] = now
        return await handler(event, data)


class UserMiddleware(BaseMiddleware):
    """Пишет пользователя в БД: он нужен и для статистики, и для рассылок."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None and not user.is_bot:
            await db.upsert_user(user.id, user.username, user.full_name)
        return await handler(event, data)


class AdminOnlyMiddleware(BaseMiddleware):
    """Ставится только на админский роутер — обычные хендлеры её не видят."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        settings = data["settings"]
        user: User | None = data.get("event_from_user")
        if not settings.is_admin(user.id if user else None):
            if isinstance(event, CallbackQuery):
                await event.answer(texts.ADMIN_DENIED, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(texts.ADMIN_DENIED)
            return None
        return await handler(event, data)
