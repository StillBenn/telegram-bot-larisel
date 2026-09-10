"""Ловушка для всего, что не поймали остальные роутеры.

Регистрируется последней. Без неё пользователь, отправивший стикер или
случайный текст, не получает вообще никакого ответа и решает, что бот умер.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from .. import texts
from ..config import Settings
from ..keyboards import main_menu

router = Router(name="fallback")


@router.message(StateFilter(None))
async def unknown_message(message: Message, settings: Settings) -> None:
    user = message.from_user
    await message.answer(
        "Не понял запрос. Выберите действие в меню ниже 👇",
        reply_markup=main_menu(settings.is_admin(user.id if user else None)),
    )


@router.callback_query()
async def unknown_callback(callback: CallbackQuery) -> None:
    """Старая кнопка из давнего сообщения. Отвечаем, чтобы снять «часики»."""
    await callback.answer(texts.ERR_STALE, show_alert=True)
