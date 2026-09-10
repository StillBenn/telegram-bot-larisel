"""Корзина: количество, удаление, переход к оформлению."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, Message

from .. import db, texts
from ..catalog import get_product
from ..keyboards import CartCB, NOOP, cart_kb, empty_cart_kb
from ..ui import edit_view

router = Router(name="cart")
# См. комментарий в configurator.py: корзину нельзя менять кнопками, пока идёт
# оформление заказа — сумма на экране подтверждения перестала бы совпадать
# с суммой созданного заказа.
router.message.filter(StateFilter(None))
router.callback_query.filter(StateFilter(None))


async def cart_view(user_id: int) -> tuple[str, object]:
    """Готовый текст + клавиатура корзины. Одна точка правды для всех входов."""
    items = await db.get_cart(user_id)
    if not items:
        return texts.CART_EMPTY, empty_cart_kb()

    names: dict[str, str] = {}
    configs: dict[int, str] = {}
    for item in items:
        product = get_product(item.product_id)
        names[item.product_id] = product.name if product else item.product_id
        configs[item.id] = (
            product.config_line(item.config) if product else ""
        )
    return texts.cart(items, names, configs), cart_kb(items)


@router.message(F.text == texts.BTN_CART)
@router.message(Command("cart"))
async def show_cart(message: Message) -> None:
    if message.from_user is None:
        return
    text, keyboard = await cart_view(message.from_user.id)
    await message.answer(text, reply_markup=keyboard)


async def _redraw(callback: CallbackQuery, text: str, keyboard: object) -> None:
    """Перерисовывает корзину, а если сообщение уже не редактируется — шлёт новое.

    Кнопки живут в старых сообщениях. Telegram не даёт править сообщение старше
    48 часов, и тогда edit молча не срабатывает: товар из базы удалён, а на
    экране он остался. Клиент жмёт ещё раз и опустошает корзину вслепую.
    """
    if await edit_view(callback, text, keyboard):
        return
    if isinstance(callback.message, Message):
        await callback.message.answer(text, reply_markup=keyboard)


@router.callback_query(CartCB.filter(F.action.in_({"inc", "dec", "drop"})))
async def change_item(callback: CallbackQuery, callback_data: CartCB) -> None:
    if callback.from_user is None:
        return
    user_id = callback.from_user.id

    if callback_data.action == "drop":
        await db.remove_item(user_id, callback_data.item)
    else:
        delta = 1 if callback_data.action == "inc" else -1
        await db.change_qty(user_id, callback_data.item, delta)

    text, keyboard = await cart_view(user_id)
    await _redraw(callback, text, keyboard)
    await callback.answer()


@router.callback_query(CartCB.filter(F.action == "clear"))
async def clear_cart(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    await db.clear_cart(callback.from_user.id)
    await _redraw(callback, texts.CART_EMPTY, empty_cart_kb())
    await callback.answer(texts.CART_CLEARED)


@router.callback_query(F.data == NOOP)
async def noop(callback: CallbackQuery) -> None:
    """Кнопка-счётчик «2 шт.» ничего не делает, но ответить Telegram обязаны:
    иначе на кнопке несколько секунд крутится индикатор загрузки."""
    await callback.answer()
