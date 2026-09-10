"""Панель администратора: статистика, заказы, смена статуса, выгрузка.

Доступ закрыт мидлварью AdminOnlyMiddleware, которая навешана на этот роутер —
проверку прав не нужно повторять в каждом хендлере.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .. import db, export, texts
from ..keyboards import (
    ADMIN_PAGE_SIZE,
    AdminCB,
    admin_list_kb,
    admin_order_kb,
    admin_panel_kb,
)
from ..ui import edit_view

log = logging.getLogger(__name__)

router = Router(name="admin")


def _status_filter(raw: str) -> str | None:
    """'-' в callback означает «без фильтра» — CallbackData не хранит None."""
    return None if raw in {"-", ""} else raw


@router.message(Command("admin"))
async def open_panel(message: Message) -> None:
    data = await db.stats()
    await message.answer(texts.admin_panel(data), reply_markup=admin_panel_kb())


@router.callback_query(AdminCB.filter(F.action == "panel"))
async def refresh_panel(callback: CallbackQuery) -> None:
    data = await db.stats()
    await edit_view(callback, texts.admin_panel(data), admin_panel_kb())
    await callback.answer()


@router.callback_query(AdminCB.filter(F.action == "list"))
async def show_list(callback: CallbackQuery, callback_data: AdminCB) -> None:
    status = _status_filter(callback_data.status)
    total = await db.count_orders(status)
    if total == 0:
        await callback.answer(texts.ADMIN_NO_ORDERS, show_alert=True)
        return

    page = max(callback_data.page, 0)
    # Страница могла «уехать» за конец списка (заказ удалили/отфильтровали).
    last_page = max((total - 1) // ADMIN_PAGE_SIZE, 0)
    page = min(page, last_page)

    orders = await db.list_orders(
        offset=page * ADMIN_PAGE_SIZE, limit=ADMIN_PAGE_SIZE, status=status
    )
    title = "📋 <b>Заказы</b>" if status is None else "🆕 <b>Новые заказы</b>"
    header = f"{title}\nВсего: {total} · страница {page + 1} из {last_page + 1}"
    await edit_view(
        callback, header, admin_list_kb(orders, page, total, callback_data.status)
    )
    await callback.answer()


@router.callback_query(AdminCB.filter(F.action == "order"))
async def show_order(callback: CallbackQuery, callback_data: AdminCB) -> None:
    order = await db.get_order(callback_data.order)
    if order is None:
        await callback.answer(texts.ERR_STALE, show_alert=True)
        return
    keyboard = admin_order_kb(order, callback_data.page, callback_data.status)
    if not await edit_view(callback, texts.admin_order(order), keyboard):
        # Уведомление о новом заказе — обычное сообщение, а не экран панели;
        # если его не получилось перерисовать, шлём карточку отдельно.
        if isinstance(callback.message, Message):
            await callback.message.answer(
                texts.admin_order(order), reply_markup=keyboard
            )
    await callback.answer()


@router.callback_query(AdminCB.filter(F.action == "status"))
async def change_status(
    callback: CallbackQuery, callback_data: AdminCB, bot: Bot
) -> None:
    new_status = callback_data.status
    if new_status not in db.STATUSES:
        await callback.answer(texts.ERR_STALE, show_alert=True)
        return

    changed = await db.set_status(callback_data.order, new_status)
    order = await db.get_order(callback_data.order)
    if order is None:
        await callback.answer(texts.ERR_STALE, show_alert=True)
        return
    if not changed:
        await callback.answer(texts.ADMIN_STATUS_SAME)
        return

    # Список после смены статуса перерисовываем без фильтра: заказ мог из него выпасть.
    await edit_view(
        callback, texts.admin_order(order), admin_order_kb(order, callback_data.page, "-")
    )

    # Уведомляем клиента ДО ответа на callback: Telegram отвечает на callback
    # ровно один раз, и второй вызов (в except) просто падал бы с 400 —
    # админ так никогда и не узнавал, что клиента предупредить не удалось.
    notice = texts.admin_status_set(order)
    if new_status in db.NOTIFY_STATUSES:
        try:
            await bot.send_message(order.user_id, texts.status_changed(order))
        except Exception as error:  # noqa: BLE001 — клиент мог заблокировать бота
            log.info("Клиент %s не получил уведомление: %s", order.user_id, error)
            await callback.answer(texts.ADMIN_NOTIFY_FAILED, show_alert=True)
            return
    await callback.answer(notice)


@router.callback_query(AdminCB.filter(F.action.in_({"export_xlsx", "export_csv"})))
async def export_orders(callback: CallbackQuery, callback_data: AdminCB) -> None:
    rows = await db.export_rows()
    if not rows:
        await callback.answer(texts.ADMIN_EXPORT_EMPTY, show_alert=True)
        return
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    if callback_data.action == "export_xlsx":
        payload, name = export.to_xlsx(rows), export.timestamped_name("xlsx")
    else:
        payload, name = export.to_csv(rows), export.timestamped_name("csv")

    await callback.message.answer_document(
        BufferedInputFile(payload, filename=name),
        caption=f"{texts.ADMIN_EXPORT_CAPTION} — строк: {len(rows)}",
    )
    await callback.answer()


@router.message(Command("stats"))
async def show_stats(message: Message) -> None:
    data = await db.stats()
    await message.answer(texts.admin_panel(data), reply_markup=admin_panel_kb())
