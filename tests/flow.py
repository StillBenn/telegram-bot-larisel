"""Сквозной тест сценария: от /start до заказа и админки — без сети.

Поднимается настоящий Dispatcher со всеми роутерами и мидлварями, а вместо
Telegram подставляется поддельная сессия, которая записывает исходящие вызовы.
Так проверяется то, что дымовой тест проверить не может: правильно ли
зарегистрированы хендлеры, срабатывают ли фильтры и не «съедает» ли один
роутер апдейты другого.

Запуск: python tests/flow.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("BOT_TOKEN", "0:TEST")

from aiogram import Bot  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.methods import TelegramMethod  # noqa: E402
from aiogram.types import (  # noqa: E402
    CallbackQuery,
    Chat,
    Contact,
    Message,
    Update,
    User,
)

from app import db  # noqa: E402
from app.config import Settings  # noqa: E402
from bot import create_dispatcher  # noqa: E402

USER_ID = 424242
CHAT_ID = 424242
BOT_ID = 111

passed = 0
failed: list[str] = []


def check(name: str, condition: bool, detail: Any = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed.append(f"{name} — {detail}")
        print(f"  FAIL {name} — {detail}")


# ------------------------------------------------------------- поддельная сессия

class FakeSession(BaseSession):
    """Ничего не отправляет, только запоминает, что бот пытался отправить."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self._message_id = 100

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        yield b""

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None):
        self.calls.append(method)
        name = type(method).__name__
        if name == "GetMe":
            return User(id=BOT_ID, is_bot=True, first_name="NORD", username="nord_demo_bot")
        if name.startswith(("Send", "Edit")) and "ReplyMarkup" not in name:
            self._message_id += 1
            return Message(
                message_id=self._message_id,
                date=datetime.now(timezone.utc),
                chat=Chat(id=CHAT_ID, type="private"),
                from_user=User(id=BOT_ID, is_bot=True, first_name="NORD"),
                text=getattr(method, "text", None) or getattr(method, "caption", None) or "",
            )
        return True

    # --- помощники для проверок ---

    def texts(self) -> list[str]:
        """Только то, что появилось в чате.

        AnswerCallbackQuery сюда не входит: всплывающая подсказка «Индиго» —
        это не экран, и путать её с содержимым сообщения нельзя.
        """
        out = []
        for call in self.calls:
            if type(call).__name__ == "AnswerCallbackQuery":
                continue
            for field in ("text", "caption"):
                value = getattr(call, field, None)
                if isinstance(value, str) and value:
                    out.append(value)
        return out

    def alerts(self) -> list[str]:
        return [
            getattr(call, "text", "") or ""
            for call in self.calls
            if type(call).__name__ == "AnswerCallbackQuery"
        ]

    def last_text(self) -> str:
        texts = self.texts()
        return texts[-1] if texts else ""

    def method_names(self) -> list[str]:
        return [type(call).__name__ for call in self.calls]

    def sent_to(self, chat_id: int) -> list[str]:
        out = []
        for call in self.calls:
            if getattr(call, "chat_id", None) == chat_id:
                value = getattr(call, "text", None) or getattr(call, "caption", None)
                if value:
                    out.append(value)
        return out

    def reset(self) -> None:
        self.calls.clear()


# ------------------------------------------------------------------ конструкторы

def _user() -> User:
    return User(id=USER_ID, is_bot=False, first_name="Бюньямин", username="Still_Benn")


def msg(text: str, message_id: int = 1) -> Update:
    return Update(
        update_id=message_id,
        message=Message(
            message_id=message_id,
            date=datetime.now(timezone.utc),
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=_user(),
            text=text,
        ),
    )


def contact_msg(phone: str, own: bool = True) -> Update:
    return Update(
        update_id=999,
        message=Message(
            message_id=999,
            date=datetime.now(timezone.utc),
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=_user(),
            contact=Contact(
                phone_number=phone,
                first_name="Бюньямин",
                user_id=USER_ID if own else 5,
            ),
        ),
    )


def cb(data: str, with_photo: bool = False) -> Update:
    message = Message(
        message_id=50,
        date=datetime.now(timezone.utc),
        chat=Chat(id=CHAT_ID, type="private"),
        from_user=User(id=BOT_ID, is_bot=True, first_name="NORD"),
        text=None if with_photo else "экран",
    )
    return Update(
        update_id=1,
        callback_query=CallbackQuery(
            id="cb1",
            from_user=_user(),
            chat_instance="ci",
            message=message,
            data=data,
        ),
    )


# ------------------------------------------------------------------------- сценарий

async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        await db.init_db(Path(tmp) / "flow.sqlite3")

        settings = Settings(
            token="0:TEST",
            admin_ids=(USER_ID,),
            viewer_url="https://example.com/3d",
            manager_url="https://t.me/example",
            shop_name="Мебельная мастерская NORD",
            db_path=Path(tmp) / "flow.sqlite3",
            assets_dir=Path(tmp) / "assets",  # фото нет -> путь текстовой карточки
        )

        session = FakeSession()
        bot = Bot(
            token="0:TEST",
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        # throttle_rate=0: апдейты в тесте идут вплотную, антиспам их бы отбросил.
        dp = create_dispatcher(settings, throttle_rate=0.0)

        async def feed(update: Update) -> None:
            await dp.feed_update(bot, update)

        print("\n[1] Старт и меню")
        await feed(msg("/start"))
        check("приветствие отправлено", "Здравствуйте" in session.last_text(), session.last_text()[:60])
        check("клавиатура меню приложена", "SendMessage" in session.method_names())

        session.reset()
        await feed(msg("ℹ️ О мастерской"))
        check("«О мастерской» отвечает", "Доставка" in session.last_text())

        print("\n[2] Конфигуратор")
        session.reset()
        await feed(msg("🪑 Собрать кресло"))
        check("карточка товара", "Кресло NORD" in session.last_text())
        check("цена «от»", "42" in session.last_text(), session.last_text()[:80])

        session.reset()
        await feed(cb("cfg:summary:chair-nord:-:-"))
        check("экран сборки открылся", "Итого" in session.last_text(), session.last_text()[:80])
        check("базовая цена на экране", "42" in session.last_text())

        session.reset()
        await feed(cb("cfg:group:chair-nord:fabric:-"))
        check("список тканей открылся", "Ткань" in session.last_text(), session.last_text()[:80])

        session.reset()
        await feed(cb("cfg:set:chair-nord:fabric:indigo"))
        check("ткань применилась", "Индиго" in session.last_text(), session.last_text()[:120])
        check("цена пересчиталась (+3 200)", "46" in session.last_text(), session.last_text())

        session.reset()
        await feed(cb("cfg:set:chair-nord:size:xl"))
        check("размер XL применился", "XL" in session.last_text())
        check("цена 53 500", "53" in session.last_text(), session.last_text())

        print("\n[3] Корзина")
        session.reset()
        await feed(cb("cfg:add:chair-nord:-:-"))
        cart_items = await db.get_cart(USER_ID)
        check("позиция в корзине", len(cart_items) == 1, len(cart_items))
        check("цена позиции 53 500", cart_items[0].unit_price == 53_500, cart_items[0].unit_price)

        session.reset()
        await feed(msg("🛒 Корзина"))
        check("корзина показана", "Корзина" in session.last_text())

        session.reset()
        await feed(cb(f"cart:inc:{cart_items[0].id}"))
        check("количество выросло", (await db.get_cart(USER_ID))[0].qty == 2)

        print("\n[4] Оформление заказа")
        session.reset()
        await feed(cb("cart:checkout:0"))
        check("шаг 1 — имя", "шаг 1" in session.last_text().lower(), session.last_text()[:80])

        await feed(msg("Я"))
        check("слишком короткое имя отклонено", "2 до 60" in session.last_text(), session.last_text()[:80])

        await feed(msg("Бюньямин Каткат"))
        check("шаг 2 — телефон", "Шаг 2" in session.last_text(), session.last_text()[:80])

        await feed(msg("абвгд"))
        check("неверный телефон отклонён", "Не похоже на номер" in session.last_text())

        await feed(contact_msg("+79999999999", own=False))
        check("чужой контакт отклонён", "Не похоже на номер" in session.last_text())

        await feed(contact_msg("89001112233"))
        check("свой контакт принят, шаг 3", "Шаг 3" in session.last_text(), session.last_text()[:80])

        await feed(msg("Москва"))
        check("шаг 4 — адрес", "Шаг 4" in session.last_text())

        await feed(msg("дом"))
        check("короткий адрес отклонён", "слишком короткий" in session.last_text().lower())

        await feed(msg("ул. Павла Корчагина, д. 22А, кв. 5"))
        check("шаг 5 — комментарий", "Шаг 5" in session.last_text())

        session.reset()
        await feed(msg("⏭ Пропустить"))
        check("экран подтверждения", "Проверьте заказ" in session.last_text(), session.last_text()[:80])
        check("телефон нормализован", "+79001112233" in session.last_text(), session.last_text())
        check("сумма 107 000", "107" in session.last_text(), session.last_text())

        session.reset()
        await feed(cb("chk:confirm"))
        orders = await db.user_orders(USER_ID)
        check("заказ создан", len(orders) == 1, len(orders))
        check("корзина очищена", await db.get_cart(USER_ID) == [])
        check("клиент получил номер заказа", "принят" in session.last_text().lower()
              or any("принят" in t for t in session.texts()), session.texts())
        check(
            "админ получил уведомление",
            any("НОВЫЙ ЗАКАЗ" in t for t in session.sent_to(USER_ID)),
            session.texts(),
        )

        print("\n[5] Мои заказы")
        session.reset()
        await feed(msg("📦 Мои заказы"))
        check("история заказов", "Мои заказы" in session.last_text())
        check("статус виден", "Новый" in session.last_text(), session.last_text()[:200])

        print("\n[6] Админка")
        session.reset()
        await feed(msg("/admin"))
        check("панель открылась", "Панель администратора" in session.last_text())
        check("выручка посчитана", "107" in session.last_text(), session.last_text())

        session.reset()
        await feed(cb("adm:list:0:0:-"))
        check("список заказов", "Заказы" in session.last_text(), session.last_text()[:80])

        order_id = orders[0].id
        session.reset()
        await feed(cb(f"adm:order:{order_id}:0:-"))
        check("карточка заказа у админа", f"Заказ №{order_id}" in session.last_text())
        check("телефон клиента виден", "+79001112233" in session.last_text())

        session.reset()
        await feed(cb(f"adm:status:{order_id}:0:confirmed"))
        updated = await db.get_order(order_id)
        check("статус изменился", updated is not None and updated.status == "confirmed")
        check(
            "клиент уведомлён о статусе",
            any("новый статус" in t.lower() for t in session.sent_to(USER_ID)),
            session.texts(),
        )

        session.reset()
        await feed(cb("adm:export_xlsx:0:0:-"))
        check("excel отправлен", "SendDocument" in session.method_names(), session.method_names())

        session.reset()
        await feed(cb("adm:export_csv:0:0:-"))
        check("csv отправлен", "SendDocument" in session.method_names(), session.method_names())

        print("\n[7] Права доступа")
        outsider = Update(
            update_id=2,
            message=Message(
                message_id=2,
                date=datetime.now(timezone.utc),
                chat=Chat(id=999, type="private"),
                from_user=User(id=999, is_bot=False, first_name="Чужой"),
                text="/admin",
            ),
        )
        session.reset()
        await feed(outsider)
        check("посторонний в админку не попал", "только администратору" in session.last_text(),
              session.last_text()[:80])

        print("\n[8] Неизвестный ввод и старые кнопки")
        session.reset()
        await feed(msg("абракадабра"))
        check("fallback ответил", "Не понял запрос" in session.last_text(), session.last_text()[:80])

        session.reset()
        await feed(cb("cfg:summary:НЕТ-ТАКОГО:-:-"))
        check(
            "битый callback не роняет бота",
            "AnswerCallbackQuery" in session.method_names(),
            session.method_names(),
        )

        await bot.session.close()

    print("\n" + "=" * 46)
    if failed:
        print(f"ПРОВАЛЕНО {len(failed)} из {passed + len(failed)}:")
        for line in failed:
            print("  -", line)
        sys.exit(1)
    print(f"ВСЕ {passed} ПРОВЕРОК ПРОЙДЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
