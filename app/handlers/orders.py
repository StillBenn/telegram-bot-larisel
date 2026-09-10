"""Мои заказы — история и текущие статусы."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import Message

from .. import db, texts

router = Router(name="orders")
router.message.filter(StateFilter(None))


@router.message(F.text == texts.BTN_ORDERS)
@router.message(Command("orders"))
async def show_orders(message: Message) -> None:
    if message.from_user is None:
        return
    orders = await db.user_orders(message.from_user.id)
    if not orders:
        await message.answer(texts.ORDERS_EMPTY)
        return
    await message.answer(texts.orders_list(orders))
