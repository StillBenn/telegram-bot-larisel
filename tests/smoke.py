"""Дымовой тест: проходит весь путь заказа без Telegram.

Запуск: python tests/smoke.py
Работает на временной базе, боевую data/larisel.sqlite3 не трогает.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Токен нужен только для загрузки настроек — сеть здесь не используется.
os.environ.setdefault("BOT_TOKEN", "0:TEST")

from app import db, export, texts  # noqa: E402
from app.catalog import CHAIR_LARISEL  # noqa: E402
from app.keyboards import (  # noqa: E402
    admin_list_kb,
    admin_order_kb,
    admin_panel_kb,
    cart_kb,
    config_kb,
    confirm_kb,
    group_kb,
    main_menu,
    phone_kb,
    product_kb,
)
from app.utils import normalize_phone  # noqa: E402

CAPTION_LIMIT = 1024
BUTTON_CALLBACK_LIMIT = 64

passed = 0
failed: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed.append(f"{name} — {detail}")
        print(f"  FAIL {name} — {detail}")


async def main() -> None:
    print("\n[1] Цены и опции")
    check("базовая цена 42 900", CHAIR_LARISEL.price(None) == 42_900, CHAIR_LARISEL.price(None))
    full = {"fabric": "terracotta", "frame": "brass", "size": "xl", "pillow": "yes"}
    check("максимальная сборка 65 300", CHAIR_LARISEL.price(full) == 65_300, CHAIR_LARISEL.price(full))
    check(
        "неизвестная опция откатывается к базовой",
        CHAIR_LARISEL.price({"frame": "ЧТО-ТО"}) == 42_900,
    )

    print("\n[2] Телефон")
    for raw, expected in (
        ("+7 900 111 22 33", "+79001112233"),
        ("89001112233", "+79001112233"),
        ("9001112233", "+79001112233"),
        ("+90 532 111 22 33", "+905321112233"),
        ("не телефон", None),
        ("", None),
        ("123", None),
    ):
        check(f"телефон {raw!r}", normalize_phone(raw) == expected, normalize_phone(raw))

    print("\n[3] База данных")
    with tempfile.TemporaryDirectory() as tmp:
        await db.init_db(Path(tmp) / "test.sqlite3")
        user_id = 777
        await db.upsert_user(user_id, "tester", "Тест Тестов")

        cfg_a = CHAIR_LARISEL.normalize({"fabric": "olive", "frame": "walnut"})
        cfg_b = CHAIR_LARISEL.normalize({"fabric": "indigo", "size": "xl", "pillow": "yes"})
        await db.add_to_cart(user_id, CHAIR_LARISEL.id, cfg_a, CHAIR_LARISEL.price(cfg_a))
        await db.add_to_cart(user_id, CHAIR_LARISEL.id, cfg_a, CHAIR_LARISEL.price(cfg_a))
        await db.add_to_cart(user_id, CHAIR_LARISEL.id, cfg_b, CHAIR_LARISEL.price(cfg_b))

        items = await db.get_cart(user_id)
        check("одинаковая сборка слилась в одну позицию", len(items) == 2, len(items))
        check("количество выросло до 2", items[0].qty == 2, items[0].qty)

        await db.change_qty(user_id, items[1].id, -1)
        check("qty 1 → 0 удаляет позицию", len(await db.get_cart(user_id)) == 1)

        await db.add_to_cart(user_id, CHAIR_LARISEL.id, cfg_b, CHAIR_LARISEL.price(cfg_b))
        items = await db.get_cart(user_id)
        total = sum(item.total for item in items)
        rows = [
            (
                item.product_id,
                CHAIR_LARISEL.name,
                CHAIR_LARISEL.config_line(item.config),
                item.config,
                item.qty,
                item.unit_price,
            )
            for item in items
        ]
        order_id = await db.create_order(
            user_id,
            "tester",
            {
                "name": "Иван Иванов",
                "phone": "+79001112233",
                "city": "Москва",
                "address": "ул. Павла Корчагина, 22А, кв. 5",
                "comment": "Позвонить после 18:00",
            },
            rows,
            total,
        )
        check("заказ создан", order_id == 1, order_id)
        check("корзина очищена транзакцией", await db.get_cart(user_id) == [])

        order = await db.get_order(order_id)
        check("позиции заказа сохранены", order is not None and len(order.items) == 2)
        check("сумма совпадает", order is not None and order.total == total)

        check("смена статуса сработала", await db.set_status(order_id, db.STATUS_CONFIRMED))
        check(
            "повторная установка того же статуса не считается изменением",
            not await db.set_status(order_id, db.STATUS_CONFIRMED),
        )

        stat = await db.stats()
        check("статистика: 1 заказ", stat["orders"] == 1, stat)
        check("статистика: выручка", stat["revenue"] == total, stat)

        await db.set_status(order_id, db.STATUS_CANCELLED)
        stat = await db.stats()
        check("отменённый заказ не в выручке", stat["revenue"] == 0, stat)

        print("\n[4] Выгрузка")
        export_rows = await db.export_rows()
        check("строк выгрузки = позиций", len(export_rows) == 2, len(export_rows))
        xlsx = export.to_xlsx(export_rows)
        check("xlsx похож на zip", xlsx[:2] == b"PK", xlsx[:4])
        csv_bytes = export.to_csv(export_rows)
        check("csv с BOM для Excel", csv_bytes.startswith(b"\xef\xbb\xbf"))
        check("csv содержит имя клиента", "Иван Иванов".encode("utf-8") in csv_bytes)

        print("\n[5] Тексты и лимиты Telegram")
        card = texts.product_card(CHAIR_LARISEL)
        check("карточка товара влезает в подпись", len(card) <= CAPTION_LIMIT, len(card))
        cfg_text = texts.configuration(CHAIR_LARISEL, full)
        check("экран сборки влезает в подпись", len(cfg_text) <= CAPTION_LIMIT, len(cfg_text))
        for group in CHAIR_LARISEL.groups:
            picker = texts.group_picker(CHAIR_LARISEL, group.id, full)
            check(
                f"экран «{group.title}» влезает в подпись",
                len(picker) <= CAPTION_LIMIT,
                len(picker),
            )

        order = await db.get_order(order_id)
        assert order is not None
        for name, text in (
            ("уведомление админу", texts.admin_new_order(order)),
            ("карточка заказа (админ)", texts.admin_order(order)),
            ("мои заказы", texts.orders_list([order])),
            ("о мастерской", texts.about("Мебельная мастерская Larisel")),
        ):
            check(f"{name} не пустой и < 4096", 0 < len(text) < 4096, len(text))

        check(
            "html экранируется",
            "&lt;b&gt;" in texts.greeting("<b>Вася", "Магазин"),
            texts.greeting("<b>Вася", "Магазин")[:60],
        )

        print("\n[6] Клавиатуры и длина callback_data")
        items = [
            db.CartItem(id=1, product_id=CHAIR_LARISEL.id, config=cfg_a, qty=2, unit_price=1),
        ]
        keyboards = {
            "главное меню": main_menu(True),
            "карточка товара": product_kb(CHAIR_LARISEL, "https://example.com"),
            "конфигуратор": config_kb(CHAIR_LARISEL, full, "https://example.com"),
            "корзина": cart_kb(items),
            "подтверждение": confirm_kb(),
            "телефон": phone_kb(),
            "панель админа": admin_panel_kb(),
            "список заказов": admin_list_kb([order], 0, 1, "-"),
            "карточка заказа": admin_order_kb(order, 0, "-"),
        }
        for group in CHAIR_LARISEL.groups:
            keyboards[f"опции «{group.title}»"] = group_kb(CHAIR_LARISEL, group.id, full)

        for name, keyboard in keyboards.items():
            rows_kb = getattr(keyboard, "inline_keyboard", None) or keyboard.keyboard
            longest = 0
            for row in rows_kb:
                for button in row:
                    data = getattr(button, "callback_data", None)
                    if data:
                        longest = max(longest, len(data.encode("utf-8")))
            check(
                f"{name}: callback_data ≤ 64 байт",
                longest <= BUTTON_CALLBACK_LIMIT,
                f"максимум {longest}",
            )

    print("\n[7] Фото товара")
    photo = Path(__file__).resolve().parent.parent / "assets" / CHAIR_LARISEL.photo
    check("файл фото на месте", photo.is_file(), photo)
    if photo.is_file():
        head = photo.read_bytes()[:3]
        size_mb = photo.stat().st_size / 1024 / 1024
        check("это JPEG", head == b"\xff\xd8\xff", head)
        # Telegram принимает фото до 10 МБ, но всё, что больше пары мегабайт,
        # заметно тормозит открытие карточки в мобильном клиенте.
        check(f"размер {size_mb:.2f} МБ в пределах 2 МБ", size_mb < 2, size_mb)

    print("\n" + "=" * 46)
    if failed:
        print(f"ПРОВАЛЕНО {len(failed)} из {passed + len(failed)}:")
        for line in failed:
            print("  -", line)
        sys.exit(1)
    print(f"ВСЕ {passed} ПРОВЕРОК ПРОЙДЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
