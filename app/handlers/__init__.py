"""Сборка роутеров.

Порядок важен: апдейт идёт по роутерам сверху вниз и останавливается на первом
подходящем хендлере. Поэтому fallback — всегда последний.
"""

from __future__ import annotations

from aiogram import Dispatcher

from ..middlewares import AdminOnlyMiddleware
from . import admin, cart, checkout, common, configurator, fallback, orders


def setup_routers(dispatcher: Dispatcher) -> None:
    admin.router.message.middleware(AdminOnlyMiddleware())
    admin.router.callback_query.middleware(AdminOnlyMiddleware())

    dispatcher.include_routers(
        common.router,
        configurator.router,
        cart.router,
        checkout.router,
        orders.router,
        admin.router,
        fallback.router,
    )
