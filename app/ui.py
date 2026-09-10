"""Помощники отображения.

Экран конфигуратора живёт в ОДНОМ сообщении, которое перерисовывается на каждое
нажатие. Поэтому нужен единый способ «изменить сообщение», не зная заранее,
это сообщение с фото (подпись) или без (текст).
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    Message,
)

log = logging.getLogger(__name__)

# file_id фотографии, уже загруженной в Telegram. Повторная отправка того же
# файла с диска — лишний трафик и задержка на каждом открытии карточки.
_photo_cache: dict[str, str] = {}


async def send_card(
    message: Message,
    text: str,
    keyboard: InlineKeyboardMarkup | None,
    photo_path: Path | None,
) -> Message:
    """Карточка товара: с фото, если оно есть, иначе обычным текстом."""
    if photo_path and photo_path.is_file():
        key = photo_path.name
        cached = _photo_cache.get(key)
        try:
            sent = await message.answer_photo(
                photo=cached or FSInputFile(photo_path),
                caption=text,
                reply_markup=keyboard,
            )
        except TelegramBadRequest:
            # Повторяем ТОЛЬКО если отправляли по кешированному file_id: он мог
            # устареть (бот переехал на другой аккаунт). Если файл слали с диска,
            # причина в другом — второй такой же запрос упадёт точно так же.
            if cached is None:
                raise
            _photo_cache.pop(key, None)
            sent = await message.answer_photo(
                photo=FSInputFile(photo_path), caption=text, reply_markup=keyboard
            )
        if sent.photo:
            _photo_cache[key] = sent.photo[-1].file_id
        return sent
    return await message.answer(text, reply_markup=keyboard)


async def edit_view(
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None
) -> bool:
    """Перерисовывает сообщение под кнопкой. False — если сообщение недоступно."""
    message = callback.message
    if not isinstance(message, Message):
        return False
    try:
        if message.photo:
            await message.edit_caption(caption=text, reply_markup=keyboard)
        else:
            await message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as error:
        # «message is not modified» — обычное дело: пользователь нажал ту же
        # кнопку второй раз. Это не ошибка, молча выходим.
        if "message is not modified" in str(error):
            return True
        log.warning("Не удалось перерисовать сообщение: %s", error)
        return False
    return True
