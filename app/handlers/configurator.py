"""Конфигуратор кресла.

Экран сборки — одно сообщение, которое перерисовывается на каждое нажатие.
Так в чате не остаётся «хвоста» из десятка промежуточных сообщений, и клиент
всё время видит актуальную цену в одном месте.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import db, texts
from ..catalog import CHAIR_LARISEL, Product, get_product
from ..config import Settings
from ..keyboards import CfgCB, config_kb, group_kb, product_kb
from ..ui import edit_view, send_card

router = Router(name="configurator")
# Фильтр стоит и на callback, а не только на message. Иначе кнопки из старой
# карточки товара продолжают работать, пока клиент оформляет заказ: он видит на
# экране подтверждения одну сумму, добавляет ещё кресло и получает заказ на
# другую. Вне сценария оформления кнопки работают как обычно.
router.message.filter(StateFilter(None))
router.callback_query.filter(StateFilter(None))

CONFIG_KEY = "config"


async def read_config(state: FSMContext, product: Product) -> dict[str, str]:
    data = await state.get_data()
    stored = data.get(CONFIG_KEY, {}).get(product.id)
    return product.normalize(stored)


async def write_config(
    state: FSMContext, product: Product, config: dict[str, str]
) -> None:
    data = await state.get_data()
    configs = dict(data.get(CONFIG_KEY, {}))
    configs[product.id] = config
    await state.update_data(**{CONFIG_KEY: configs})


@router.message(F.text == texts.BTN_CONFIGURE)
@router.message(Command("configure"))
async def open_product(message: Message, settings: Settings) -> None:
    product = CHAIR_LARISEL
    photo = settings.assets_dir / product.photo if product.photo else None
    await send_card(
        message,
        texts.product_card(product),
        product_kb(product, settings.viewer_url),
        photo,
    )


@router.callback_query(CfgCB.filter(F.action == "summary"))
async def show_summary(
    callback: CallbackQuery,
    callback_data: CfgCB,
    state: FSMContext,
    settings: Settings,
) -> None:
    product = get_product(callback_data.product)
    if product is None:
        await callback.answer(texts.ERR_STALE, show_alert=True)
        return
    config = await read_config(state, product)
    await edit_view(
        callback,
        texts.configuration(product, config),
        config_kb(product, config, settings.viewer_url),
    )
    await callback.answer()


@router.callback_query(CfgCB.filter(F.action == "group"))
async def show_group(
    callback: CallbackQuery, callback_data: CfgCB, state: FSMContext
) -> None:
    product = get_product(callback_data.product)
    if product is None or product.group(callback_data.group) is None:
        await callback.answer(texts.ERR_STALE, show_alert=True)
        return
    config = await read_config(state, product)
    await edit_view(
        callback,
        texts.group_picker(product, callback_data.group, config),
        group_kb(product, callback_data.group, config),
    )
    await callback.answer()


@router.callback_query(CfgCB.filter(F.action == "set"))
async def set_option(
    callback: CallbackQuery,
    callback_data: CfgCB,
    state: FSMContext,
    settings: Settings,
) -> None:
    product = get_product(callback_data.product)
    group = product.group(callback_data.group) if product else None
    if product is None or group is None:
        await callback.answer(texts.ERR_STALE, show_alert=True)
        return

    config = await read_config(state, product)
    config[group.id] = group.get(callback_data.option).id
    await write_config(state, product, config)

    # После выбора возвращаем на общий экран: клиент сразу видит, как
    # изменилась итоговая цена, а не остаётся внутри списка опций.
    await edit_view(
        callback,
        texts.configuration(product, config),
        config_kb(product, config, settings.viewer_url),
    )
    await callback.answer(group.get(callback_data.option).name)


@router.callback_query(CfgCB.filter(F.action == "reset"))
async def reset_config(
    callback: CallbackQuery,
    callback_data: CfgCB,
    state: FSMContext,
    settings: Settings,
) -> None:
    product = get_product(callback_data.product)
    if product is None:
        await callback.answer(texts.ERR_STALE, show_alert=True)
        return
    config = product.default_config()
    await write_config(state, product, config)
    await edit_view(
        callback,
        texts.configuration(product, config),
        config_kb(product, config, settings.viewer_url),
    )
    await callback.answer("Сброшено к базовой сборке")


@router.callback_query(CfgCB.filter(F.action == "add"))
async def add_to_cart(
    callback: CallbackQuery, callback_data: CfgCB, state: FSMContext
) -> None:
    product = get_product(callback_data.product)
    if product is None or callback.from_user is None:
        await callback.answer(texts.ERR_STALE, show_alert=True)
        return
    config = await read_config(state, product)
    added = await db.add_to_cart(
        callback.from_user.id, product.id, config, product.price(config)
    )
    if not added:
        await callback.answer(texts.CART_LIMIT_REACHED, show_alert=True)
        return
    await callback.answer("Добавлено в корзину ✅")
    if isinstance(callback.message, Message):
        await callback.message.answer(texts.added_to_cart(product, config))
