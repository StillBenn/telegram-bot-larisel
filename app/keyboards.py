"""Клавиатуры.

Callback-данные собираются через CallbackData-фабрики, а не через строки вида
"cfg:fabric:oak". Фабрика сама валидирует типы при разборе, поэтому подделанный
или устаревший callback не превращается в исключение внутри хендлера.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from .catalog import Product
from .db import CartItem, Order, STATUSES
from .texts import (
    BTN_ABOUT,
    BTN_CANCEL,
    BTN_CART,
    BTN_CONFIGURE,
    BTN_MANAGER,
    BTN_ORDERS,
    BTN_SKIP,
)
from .utils import format_price

NOOP = "noop"


class CfgCB(CallbackData, prefix="cfg"):
    action: str          # summary | group | set | add | reset
    product: str
    group: str = "-"
    option: str = "-"


class CartCB(CallbackData, prefix="cart"):
    action: str          # show | inc | dec | drop | clear | checkout
    item: int = 0


class CheckoutCB(CallbackData, prefix="chk"):
    action: str          # confirm | cancel | skip


class AdminCB(CallbackData, prefix="adm"):
    action: str          # panel | list | order | status | export_xlsx | export_csv
    order: int = 0
    page: int = 0
    status: str = "-"


# ------------------------------------------------------------------ главное меню

def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text=BTN_CONFIGURE))
    builder.add(KeyboardButton(text=BTN_CART))
    builder.add(KeyboardButton(text=BTN_ORDERS))
    builder.add(KeyboardButton(text=BTN_ABOUT))
    builder.add(KeyboardButton(text=BTN_MANAGER))
    builder.adjust(1, 2, 2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


# ------------------------------------------------------------------ конфигуратор

def product_kb(product: Product, viewer_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⚙️ Собрать под себя",
        callback_data=CfgCB(action="summary", product=product.id),
    )
    if viewer_url:
        builder.button(text="🌐 Посмотреть в 3D", url=viewer_url)
    builder.adjust(1)
    return builder.as_markup()


def config_kb(
    product: Product, config: dict[str, str], viewer_url: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for group, option in product.selected(config):
        builder.button(
            text=f"{group.emoji} {group.title}: {option.name}",
            callback_data=CfgCB(action="group", product=product.id, group=group.id),
        )
    builder.adjust(1)

    extra = InlineKeyboardBuilder()
    if viewer_url:
        extra.button(text="🌐 Посмотреть в 3D", url=viewer_url)
    extra.button(
        text=f"🛒 В корзину — {format_price(product.price(config))}",
        callback_data=CfgCB(action="add", product=product.id),
    )
    extra.button(
        text="♻️ Сбросить",
        callback_data=CfgCB(action="reset", product=product.id),
    )
    extra.adjust(1)
    builder.attach(extra)
    return builder.as_markup()


def group_kb(
    product: Product, group_id: str, config: dict[str, str]
) -> InlineKeyboardMarkup:
    group = product.group(group_id)
    builder = InlineKeyboardBuilder()
    if group is None:
        builder.button(
            text="◀️ Назад",
            callback_data=CfgCB(action="summary", product=product.id),
        )
        return builder.as_markup()

    current_id = group.get(config.get(group_id)).id
    for option in group.options:
        mark = "✅ " if option.id == current_id else f"{option.emoji} "
        extra = f" · +{format_price(option.price)}" if option.price else ""
        builder.button(
            text=f"{mark}{option.name}{extra}",
            callback_data=CfgCB(
                action="set", product=product.id, group=group.id, option=option.id
            ),
        )
    builder.button(
        text="◀️ Назад к сборке",
        callback_data=CfgCB(action="summary", product=product.id),
    )
    builder.adjust(1)
    return builder.as_markup()


# ---------------------------------------------------------------------- корзина

def cart_kb(items: list[CartItem]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, item in enumerate(items, start=1):
        row = InlineKeyboardBuilder()
        row.button(text="➖", callback_data=CartCB(action="dec", item=item.id))
        row.button(text=f"{index}) {item.qty} шт.", callback_data=NOOP)
        row.button(text="➕", callback_data=CartCB(action="inc", item=item.id))
        row.button(text="🗑", callback_data=CartCB(action="drop", item=item.id))
        row.adjust(4)
        builder.attach(row)

    footer = InlineKeyboardBuilder()
    footer.button(text="✅ Оформить заказ", callback_data=CartCB(action="checkout"))
    footer.button(
        text="➕ Собрать ещё одно",
        callback_data=CfgCB(action="summary", product="chair-nord"),
    )
    footer.button(text="🧹 Очистить корзину", callback_data=CartCB(action="clear"))
    footer.adjust(1)
    builder.attach(footer)
    return builder.as_markup()


def empty_cart_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🪑 Собрать кресло",
        callback_data=CfgCB(action="summary", product="chair-nord"),
    )
    return builder.as_markup()


# ------------------------------------------------------------------- оформление

def phone_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="📞 Отправить телефон", request_contact=True))
    builder.add(KeyboardButton(text=BTN_CANCEL))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text=BTN_CANCEL))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def skip_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text=BTN_SKIP))
    builder.add(KeyboardButton(text=BTN_CANCEL))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить заказ", callback_data=CheckoutCB(action="confirm"))
    builder.button(text=BTN_CANCEL, callback_data=CheckoutCB(action="cancel"))
    builder.adjust(1)
    return builder.as_markup()


def manager_kb(manager_url: str) -> InlineKeyboardMarkup | None:
    if not manager_url:
        return None
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Написать менеджеру", url=manager_url)
    return builder.as_markup()


# ---------------------------------------------------------------------- админка

ADMIN_PAGE_SIZE = 5


def admin_panel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Заказы", callback_data=AdminCB(action="list", page=0))
    builder.button(
        text="🆕 Только новые",
        callback_data=AdminCB(action="list", page=0, status="new"),
    )
    builder.button(text="📊 Excel", callback_data=AdminCB(action="export_xlsx"))
    builder.button(text="📄 CSV", callback_data=AdminCB(action="export_csv"))
    builder.button(text="🔄 Обновить", callback_data=AdminCB(action="panel"))
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def admin_list_kb(
    orders: list[Order], page: int, total: int, status: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        builder.button(
            text=f"№{order.id} · {format_price(order.total)} · {order.status_label}",
            callback_data=AdminCB(action="order", order=order.id, page=page, status=status),
        )
    builder.adjust(1)

    nav = InlineKeyboardBuilder()
    if page > 0:
        nav.button(
            text="◀️",
            callback_data=AdminCB(action="list", page=page - 1, status=status),
        )
    if (page + 1) * ADMIN_PAGE_SIZE < total:
        nav.button(
            text="▶️",
            callback_data=AdminCB(action="list", page=page + 1, status=status),
        )
    nav.adjust(2)
    builder.attach(nav)

    builder.attach(_single("⬅️ В панель", AdminCB(action="panel")))
    return builder.as_markup()


def admin_order_kb(order: Order, page: int, status: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, label in STATUSES.items():
        if code == order.status:
            continue
        builder.button(
            text=label,
            callback_data=AdminCB(
                action="status", order=order.id, page=page, status=code
            ),
        )
    builder.adjust(2)
    builder.attach(_single("⬅️ К списку", AdminCB(action="list", page=page, status=status)))
    return builder.as_markup()


def _single(text: str, callback: CallbackData) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text=text, callback_data=callback)
    builder.adjust(1)
    return builder


def admin_new_order_kb(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📄 Открыть заказ", callback_data=AdminCB(action="order", order=order_id)
    )
    return builder.as_markup()
