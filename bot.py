"""Точка входа.

Запуск:  python bot.py
Остановка: Ctrl+C
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from aiogram.utils.token import TokenValidationError

from app import db
from app.config import ConfigError, Settings, load_settings
from app.handlers import setup_routers
from app.middlewares import ThrottlingMiddleware, UserMiddleware

log = logging.getLogger("nord")

USER_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="configure", description="Собрать кресло"),
    BotCommand(command="cart", description="Корзина"),
    BotCommand(command="orders", description="Мои заказы"),
    BotCommand(command="help", description="Справка"),
]

ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="admin", description="Панель администратора"),
    BotCommand(command="stats", description="Статистика"),
]


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def set_commands(bot: Bot, settings: Settings) -> None:
    """Меню команд: у админов оно шире, чем у клиентов."""
    await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
    for admin_id in settings.admin_ids:
        try:
            await bot.set_my_commands(
                ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id)
            )
        except Exception as error:  # noqa: BLE001 — админ мог не запускать бота
            log.warning("Команды для админа %s не установлены: %s", admin_id, error)


def create_dispatcher(settings: Settings, throttle_rate: float = 0.4) -> Dispatcher:
    """Собранный диспетчер. Вынесено из main(), чтобы тесты поднимали то же самое."""
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["settings"] = settings

    # Антиспам — только на кнопки. На сообщениях он вреден: человек, вставивший
    # имя и телефон двумя сообщениями подряд, потерял бы второе, и бот выглядел
    # бы зависшим. У кнопок обратная задача — гасить дребезг быстрых нажатий.
    dispatcher.callback_query.middleware(ThrottlingMiddleware(rate=throttle_rate))
    for observer in (dispatcher.message, dispatcher.callback_query):
        observer.middleware(UserMiddleware())

    setup_routers(dispatcher)
    return dispatcher


async def main() -> None:
    setup_logging()
    settings = load_settings()

    await db.init_db(settings.db_path)

    bot = Bot(
        token=settings.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # Bot создан — дальше всё в try/finally, иначе падение на get_me() оставит
    # HTTP-сессию открытой («Unclosed client session» в логе).
    try:
        dispatcher = create_dispatcher(settings)

        me = await bot.get_me()
        log.info("Бот запущен: @%s (id %s)", me.username, me.id)
        if not settings.admin_ids:
            log.warning(
                "ADMIN_IDS пуст — уведомления о заказах приходить не будут. "
                "Узнайте свой ID командой /whoami и впишите его в .env"
            )

        await set_commands(bot, settings)
        # Пропускаем апдейты, накопившиеся, пока бот был выключен: отвечать на
        # заказ трёхдневной давности хуже, чем не отвечать вовсе.
        await bot.delete_webhook(drop_pending_updates=True)

        await dispatcher.start_polling(
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nБот остановлен.")
    except ConfigError as error:
        # Понятное сообщение вместо стектрейса на типовой ошибке настройки.
        # Ловим свой класс, а не RuntimeError: иначе сюда попадал бы любой
        # посторонний RuntimeError и выглядел бы как ошибка настройки.
        print(f"\n{error}\n")
        sys.exit(1)
    except TokenValidationError:
        print(
            "\nBOT_TOKEN выглядит некорректно.\n"
            "Скопируйте токен от @BotFather целиком, вместе с цифрами до двоеточия.\n"
        )
        sys.exit(1)
