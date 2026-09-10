"""Состояния оформления заказа (FSM).

Один класс — один сценарий. Пока пользователь внутри Checkout, обычные кнопки
меню не срабатывают: хендлеры оформления зарегистрированы с фильтром состояния.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Checkout(StatesGroup):
    name = State()
    phone = State()
    city = State()
    address = State()
    comment = State()
    confirm = State()
