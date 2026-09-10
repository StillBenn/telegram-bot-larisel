"""Старт, главное меню, справка, контакты."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .. import texts
from ..config import Settings
from ..keyboards import main_menu, manager_kb

router = Router(name="common")

# Все хендлеры этого роутера работают только вне сценария оформления заказа:
# иначе «ℹ️ О мастерской» посреди ввода адреса выбросит пользователя из FSM.
router.message.filter(StateFilter(None))


@router.message(CommandStart())
async def cmd_start(message: Message, settings: Settings, state: FSMContext) -> None:
    await state.set_state(None)
    user = message.from_user
    name = user.first_name if user else "гость"
    await message.answer(
        texts.greeting(name, settings.shop_name),
        reply_markup=main_menu(settings.is_admin(user.id if user else None)),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP)


@router.message(F.text == texts.BTN_ABOUT)
@router.message(Command("about"))
async def show_about(message: Message, settings: Settings) -> None:
    await message.answer(texts.about(settings.shop_name))


@router.message(Command("whoami"))
async def whoami(message: Message, settings: Settings) -> None:
    """Нужна при установке: сюда смотрят, чтобы узнать свой ID для ADMIN_IDS."""
    user = message.from_user
    is_admin = settings.is_admin(user.id if user else None)
    await message.answer(
        f"Ваш Telegram ID: <code>{user.id if user else '—'}</code>\n"
        f"Права администратора: {'есть' if is_admin else 'нет'}"
    )


@router.message(F.text == texts.BTN_MANAGER)
async def show_manager(message: Message, settings: Settings) -> None:
    keyboard = manager_kb(settings.manager_url)
    await message.answer(
        "💬 Менеджер отвечает с 10:00 до 20:00 по московскому времени.",
        reply_markup=keyboard,
    )
