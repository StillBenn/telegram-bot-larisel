"""Оформление заказа — пошаговый сценарий (FSM).

Каждый шаг проверяет ввод и при ошибке остаётся на месте, а не проваливается
дальше с мусором в данных. Корзина перечитывается из базы в момент
подтверждения: между «Оформить» и «Подтвердить» она могла измениться.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import db, texts
from ..catalog import CHAIR_LARISEL, get_product
from ..config import Settings
from ..keyboards import (
    CartCB,
    CheckoutCB,
    admin_new_order_kb,
    cancel_kb,
    confirm_kb,
    main_menu,
    phone_kb,
    skip_kb,
)
from ..states import Checkout
from ..utils import format_price, normalize_phone

log = logging.getLogger(__name__)

router = Router(name="checkout")

CHECKOUT_KEY = "checkout"
CART_SIG_KEY = "cart_signature"


def cart_signature(items: list[db.CartItem]) -> str:
    """Отпечаток корзины: что именно клиент видел на экране подтверждения.

    Клиент подтверждает КОНКРЕТНУЮ сумму. Если между показом экрана и нажатием
    «Подтвердить» корзина изменилась — со второго устройства или старой кнопкой
    из прошлого сообщения — создавать заказ по новой сумме нельзя: клиент её
    не видел и не соглашался на неё.
    """
    return ";".join(
        f"{item.id}x{item.qty}@{item.unit_price}" for item in sorted(items, key=lambda i: i.id)
    )

# Нажатие кнопки меню внутри сценария — это не имя и не адрес, а попытка уйти.
MENU_TEXTS = frozenset(texts.MENU_BUTTONS)


async def _customer(state: FSMContext) -> dict[str, str]:
    data = await state.get_data()
    return dict(data.get(CHECKOUT_KEY, {}))


async def _remember(state: FSMContext, **fields: str) -> dict[str, str]:
    customer = await _customer(state)
    customer.update(fields)
    await state.update_data(**{CHECKOUT_KEY: customer})
    return customer


async def _finish(state: FSMContext) -> None:
    """Выходим из сценария, но НЕ трогаем собранную конфигурацию кресла."""
    await state.set_state(None)
    await state.update_data(**{CHECKOUT_KEY: {}})


def _menu_press(message: Message) -> bool:
    """Не ответ на вопрос, а попытка уйти: кнопка меню или команда.

    Без проверки на «/» команда становится валидным ответом: «/start» проходит
    как имя (2–60 символов), и в мастерскую падает заказ от клиента «/start».
    """
    text = (message.text or "").strip()
    return text in MENU_TEXTS or text.startswith("/")


# ------------------------------------------------------------------------ старт

@router.callback_query(CartCB.filter(F.action == "checkout"))
async def start_checkout(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    items = await db.get_cart(callback.from_user.id)
    if not items:
        await callback.answer(texts.CART_EMPTY_ON_CHECKOUT, show_alert=True)
        return
    await state.set_state(Checkout.name)
    await state.update_data(**{CHECKOUT_KEY: {}})
    await callback.message.answer(texts.ASK_NAME, reply_markup=cancel_kb())
    await callback.answer()


# ------------------------------------------------------------------------ отмена

@router.message(StateFilter(Checkout), F.text == texts.BTN_CANCEL)
@router.message(StateFilter(Checkout), Command("cancel"))
@router.message(StateFilter(Checkout), CommandStart())
async def cancel_checkout(
    message: Message, state: FSMContext, settings: Settings
) -> None:
    """/start внутри сценария — это «выпустите меня отсюда».

    Роутер common отфильтрован по StateFilter(None), поэтому до него /start
    в оформлении не доходит: обработать выход надо здесь.
    """
    await _finish(state)
    user = message.from_user
    await message.answer(
        texts.CHECKOUT_CANCELLED,
        reply_markup=main_menu(settings.is_admin(user.id if user else None)),
    )


@router.callback_query(StateFilter(Checkout), CheckoutCB.filter(F.action == "cancel"))
async def cancel_from_button(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await _finish(state)
    if isinstance(callback.message, Message):
        user = callback.from_user
        await callback.message.answer(
            texts.CHECKOUT_CANCELLED,
            reply_markup=main_menu(settings.is_admin(user.id if user else None)),
        )
    await callback.answer()


# -------------------------------------------------------------------- шаги ввода

@router.message(Checkout.name)
async def step_name(message: Message, state: FSMContext) -> None:
    if _menu_press(message):
        await message.answer(texts.ASK_NAME, reply_markup=cancel_kb())
        return
    name = (message.text or "").strip()
    if not 2 <= len(name) <= 60:
        await message.answer(texts.ERR_NAME if message.text else texts.ERR_TEXT_EXPECTED)
        return
    await _remember(state, name=name)
    await state.set_state(Checkout.phone)
    await message.answer(texts.ASK_PHONE, reply_markup=phone_kb())


@router.message(Checkout.phone, F.contact)
async def step_phone_contact(message: Message, state: FSMContext) -> None:
    contact = message.contact
    # Чужой контакт из адресной книги — не номер заказчика. Просим свой.
    if contact is None or (
        message.from_user and contact.user_id != message.from_user.id
    ):
        await message.answer(texts.ERR_PHONE, reply_markup=phone_kb())
        return
    phone = normalize_phone(contact.phone_number) or contact.phone_number
    await _remember(state, phone=phone)
    await state.set_state(Checkout.city)
    await message.answer(texts.ASK_CITY, reply_markup=cancel_kb())


@router.message(Checkout.phone)
async def step_phone_text(message: Message, state: FSMContext) -> None:
    if _menu_press(message):
        await message.answer(texts.ASK_PHONE, reply_markup=phone_kb())
        return
    phone = normalize_phone(message.text or "")
    if phone is None:
        await message.answer(texts.ERR_PHONE, reply_markup=phone_kb())
        return
    await _remember(state, phone=phone)
    await state.set_state(Checkout.city)
    await message.answer(texts.ASK_CITY, reply_markup=cancel_kb())


@router.message(Checkout.city)
async def step_city(message: Message, state: FSMContext) -> None:
    if _menu_press(message):
        await message.answer(texts.ASK_CITY, reply_markup=cancel_kb())
        return
    city = (message.text or "").strip()
    if not 2 <= len(city) <= 60:
        await message.answer(texts.ERR_CITY if message.text else texts.ERR_TEXT_EXPECTED)
        return
    await _remember(state, city=city)
    await state.set_state(Checkout.address)
    await message.answer(texts.ASK_ADDRESS, reply_markup=cancel_kb())


@router.message(Checkout.address)
async def step_address(message: Message, state: FSMContext) -> None:
    if _menu_press(message):
        await message.answer(texts.ASK_ADDRESS, reply_markup=cancel_kb())
        return
    address = (message.text or "").strip()
    if not 5 <= len(address) <= 200:
        await message.answer(
            texts.ERR_ADDRESS if message.text else texts.ERR_TEXT_EXPECTED
        )
        return
    await _remember(state, address=address)
    await state.set_state(Checkout.comment)
    await message.answer(texts.ASK_COMMENT, reply_markup=skip_kb())


@router.message(Checkout.comment)
async def step_comment(message: Message, state: FSMContext) -> None:
    if _menu_press(message):
        await message.answer(texts.ASK_COMMENT, reply_markup=skip_kb())
        return
    raw = (message.text or "").strip()
    comment = "" if raw == texts.BTN_SKIP else raw
    if len(comment) > 500:
        await message.answer(texts.ERR_COMMENT)
        return
    customer = await _remember(state, comment=comment)
    if message.from_user is None:
        return
    await _show_confirmation(message, message.from_user.id, state, customer)


async def _show_confirmation(
    message: Message, user_id: int, state: FSMContext, customer: dict[str, str]
) -> None:
    """user_id передаём явно: у сообщения под инлайн-кнопкой from_user — это БОТ,
    и корзину пришлось бы читать не у того человека."""
    items = await db.get_cart(user_id)
    if not items:
        await _finish(state)
        await message.answer(texts.CART_EMPTY_ON_CHECKOUT, reply_markup=main_menu())
        return

    lines: list[str] = []
    total = 0
    for item in items:
        product = get_product(item.product_id)
        name = product.name if product else item.product_id
        config_line = product.config_line(item.config) if product else ""
        total += item.total
        lines.append(
            f"• <b>{texts.esc(name)}</b> — <i>{texts.esc(config_line)}</i>\n"
            f"  {item.qty} × {format_price(item.unit_price)} = "
            f"{format_price(item.total)}"
        )

    await state.set_state(Checkout.confirm)
    await state.update_data(**{CART_SIG_KEY: cart_signature(items)})
    await message.answer(
        texts.confirm(customer, "\n".join(lines), total),
        reply_markup=confirm_kb(),
    )


# -------------------------------------------------------------------- подтверждение

@router.message(Checkout.confirm)
async def confirm_needs_button(message: Message) -> None:
    """В состоянии подтверждения ждём нажатия кнопки, а не текста."""
    await message.answer("Нажмите кнопку под сообщением: подтвердить или отменить.")


@router.callback_query(Checkout.confirm, CheckoutCB.filter(F.action == "confirm"))
async def confirm_order(
    callback: CallbackQuery, state: FSMContext, settings: Settings, bot: Bot
) -> None:
    user = callback.from_user
    if user is None or not isinstance(callback.message, Message):
        return

    items = await db.get_cart(user.id)
    if not items:
        await _finish(state)
        await callback.message.answer(
            texts.CART_EMPTY_ON_CHECKOUT, reply_markup=main_menu()
        )
        await callback.answer()
        return

    data = await state.get_data()
    if data.get(CART_SIG_KEY) != cart_signature(items):
        # Заказ НЕ создаём: показываем актуальный состав и ждём нового согласия.
        await callback.message.answer(texts.CART_CHANGED_ON_CONFIRM)
        await _show_confirmation(
            callback.message, user.id, state, await _customer(state)
        )
        await callback.answer()
        return

    customer = await _customer(state)
    required = ("name", "phone", "city", "address")
    if not all(customer.get(field) for field in required):
        # Данные потерялись (перезапуск бота при MemoryStorage) — начинаем заново.
        await _finish(state)
        await callback.message.answer(texts.ERR_STALE, reply_markup=main_menu())
        await callback.answer()
        return

    rows = []
    total = 0
    for item in items:
        product = get_product(item.product_id)
        name = product.name if product else item.product_id
        config_line = product.config_line(item.config) if product else ""
        total += item.total
        rows.append(
            (item.product_id, name, config_line, item.config, item.qty, item.unit_price)
        )

    order_id = await db.create_order(user.id, user.username, customer, rows, total)
    await _finish(state)

    # Кнопки подтверждения убираем, чтобы заказ нельзя было создать дважды.
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001 — сообщение могло быть удалено пользователем
        pass

    await callback.message.answer(
        texts.order_created(order_id, total, CHAIR_LARISEL.lead_days),
        reply_markup=main_menu(settings.is_admin(user.id)),
    )
    await callback.answer("Заказ оформлен ✅")
    await notify_admins(bot, settings, order_id)


async def notify_admins(bot: Bot, settings: Settings, order_id: int) -> None:
    """Заказ уже сохранён, поэтому сбой уведомления не должен ронять хендлер."""
    if not settings.admin_ids:
        log.warning("ADMIN_IDS не заданы — заказ №%s никому не отправлен", order_id)
        return
    order = await db.get_order(order_id)
    if order is None:
        return
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                texts.admin_new_order(order),
                reply_markup=admin_new_order_kb(order.id),
            )
        except Exception as error:  # noqa: BLE001
            log.warning("Не удалось уведомить админа %s: %s", admin_id, error)
