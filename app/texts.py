"""Все тексты бота в одном месте.

Правило: ни одной русской строки в хендлерах. Захотели поменять формулировку —
меняете только этот файл. Разметка везде HTML (parse_mode=HTML).

Данные, введённые пользователем, обязательно проходят через esc() — иначе
имя вида «<b>Вася» сломает разметку сообщения у администратора.
"""

from __future__ import annotations

from html import escape

from .catalog import Product
from .db import MAX_POSITIONS, Order
from .utils import format_price, format_dt, lead_time_text, ready_date

SEP = "━" * 14


def esc(value: object) -> str:
    return escape(str(value or ""), quote=False)


# ----------------------------------------------------------------------- меню

BTN_CONFIGURE = "🪑 Собрать кресло"
BTN_CART = "🛒 Корзина"
BTN_ORDERS = "📦 Мои заказы"
BTN_ABOUT = "ℹ️ О мастерской"
BTN_MANAGER = "💬 Менеджер"

# Кнопки сценария оформления. Держим здесь, а не в keyboards.py: клавиатура и
# фильтр хендлера должны сравниваться с ОДНОЙ строкой. Разъедутся на один
# невидимый символ (U+FE0F в эмодзи) — «Отменить» молча перестанет работать.
BTN_CANCEL = "✖️ Отменить"
BTN_SKIP = "⏭ Пропустить"

MENU_BUTTONS = (BTN_CONFIGURE, BTN_CART, BTN_ORDERS, BTN_ABOUT, BTN_MANAGER)


def greeting(name: str, shop_name: str) -> str:
    return (
        f"Здравствуйте, <b>{esc(name)}</b>!\n\n"
        f"Это бот мастерской <b>{esc(shop_name)}</b>. "
        "Здесь можно собрать кресло под свой интерьер, посмотреть его в 3D "
        "и оформить заказ — без звонков и переписки.\n\n"
        "Нажмите <b>«Собрать кресло»</b>, чтобы начать."
    )


def about(shop_name: str) -> str:
    return (
        f"ℹ️ <b>{esc(shop_name)}</b>\n\n"
        "Делаем мягкую мебель под заказ с 2014 года. Каркасы — массив бука и дуба, "
        "наполнение — ППУ высокой плотности, чехлы съёмные.\n\n"
        f"{SEP}\n"
        "🚚 <b>Доставка</b>\n"
        "По Москве и области — бесплатно от 40 000 ₽. По России — транспортной "
        "компанией, стоимость считает менеджер.\n\n"
        "💳 <b>Оплата</b>\n"
        "50% предоплата, 50% при получении. Карта, счёт для юрлиц.\n\n"
        "🛡 <b>Гарантия</b>\n"
        "24 месяца на каркас и механизмы.\n\n"
        f"{SEP}\n"
        "Команды: /start — в начало, /cart — корзина, /help — справка."
    )


HELP = (
    "🧭 <b>Справка</b>\n\n"
    "/start — главное меню\n"
    "/configure — собрать кресло\n"
    "/cart — корзина\n"
    "/orders — мои заказы\n"
    "/help — эта справка\n\n"
    "Оформление заказа можно прервать в любой момент кнопкой "
    "<b>«Отменить»</b> — собранная корзина при этом сохранится."
)


# --------------------------------------------------------------- конфигуратор

def product_card(product: Product) -> str:
    return (
        f"🪑 <b>{esc(product.name)}</b>\n"
        f"<i>{esc(product.subtitle)}</i>\n\n"
        f"{esc(product.description)}\n\n"
        f"Цена от <b>{format_price(product.base_price)}</b>\n"
        f"⏱ Срок изготовления — {lead_time_text(product.lead_days)}"
    )


def configuration(product: Product, config: dict[str, str]) -> str:
    lines = [
        f"🪑 <b>{esc(product.name)}</b>",
        f"<i>{esc(product.subtitle)}</i>",
        "",
    ]
    for group, option in product.selected(config):
        line = f"{group.emoji} {esc(group.title)} — <b>{esc(option.name)}</b>"
        if option.note:
            line += f"\n<i>       {esc(option.note)}</i>"
        lines.append(line)

    total = product.price(config)
    lines += [
        "",
        f"💰 Итого: <b>{format_price(total)}</b>",
        f"⏱ Готово примерно к {ready_date(product.lead_days)} "
        f"({lead_time_text(product.lead_days)})",
        "",
        "<i>Нажмите на параметр, чтобы изменить его.</i>",
    ]
    return "\n".join(lines)


def group_picker(product: Product, group_id: str, config: dict[str, str]) -> str:
    group = product.group(group_id)
    if group is None:
        return configuration(product, config)
    current = group.get(config.get(group_id))
    lines = [f"{group.emoji} <b>{esc(group.title)}</b>"]
    if group.hint:
        lines.append(f"<i>{esc(group.hint)}</i>")
    lines += [
        "",
        f"Сейчас выбрано: <b>{esc(current.name)}</b>",
        "",
        f"💰 Текущая цена: <b>{format_price(product.price(config))}</b>",
    ]
    return "\n".join(lines)


def added_to_cart(product: Product, config: dict[str, str]) -> str:
    return (
        f"✅ Добавлено в корзину:\n"
        f"<b>{esc(product.name)}</b> — {esc(product.config_line(config))}\n"
        f"{format_price(product.price(config))}"
    )


# --------------------------------------------------------------------- корзина

CART_EMPTY = (
    "🛒 <b>Корзина пуста</b>\n\n"
    "Соберите кресло — и оно появится здесь."
)


def cart(items: list, product_names: dict[str, str], product_configs: dict[int, str]) -> str:
    lines = ["🛒 <b>Корзина</b>", ""]
    total = 0
    for index, item in enumerate(items, start=1):
        total += item.total
        name = product_names.get(item.product_id, item.product_id)
        lines += [
            f"<b>{index}. {esc(name)}</b>",
            f"<i>{esc(product_configs.get(item.id, ''))}</i>",
            f"{item.qty} × {format_price(item.unit_price)} = "
            f"<b>{format_price(item.total)}</b>",
            "",
        ]
    positions = sum(item.qty for item in items)
    lines += [
        SEP,
        f"Итого: <b>{positions}</b> шт. на <b>{format_price(total)}</b>",
    ]
    return "\n".join(lines)


CART_CLEARED = "🧹 Корзина очищена."

# Предел берём из db, а не пишем число второй раз: разъедутся — клиент увидит
# «уже 15», когда на самом деле лимит другой.
CART_LIMIT_REACHED = (
    f"В корзине уже {MAX_POSITIONS} разных сборок — "
    "больше в одно сообщение не помещается.\n"
    "Оформите заказ или удалите лишнее."
)


# ------------------------------------------------------------------ оформление

ASK_NAME = (
    "📝 <b>Оформление заказа</b> — шаг 1 из 5\n\n"
    "Как к вам обращаться? Напишите имя и фамилию."
)
ASK_PHONE = (
    "📞 <b>Шаг 2 из 5</b>\n\n"
    "Оставьте телефон для связи — нажмите кнопку ниже "
    "или напишите номер вручную."
)
ASK_CITY = "🏙 <b>Шаг 3 из 5</b>\n\nВ какой город доставить?"
ASK_ADDRESS = (
    "🏠 <b>Шаг 4 из 5</b>\n\n"
    "Адрес доставки: улица, дом, квартира, этаж."
)
ASK_COMMENT = (
    "💬 <b>Шаг 5 из 5</b>\n\n"
    "Комментарий к заказу — удобное время, домофон, пожелания.\n"
    "Если добавить нечего, нажмите «Пропустить»."
)

ERR_NAME = "Имя должно быть от 2 до 60 символов. Напишите, пожалуйста, ещё раз."
ERR_PHONE = (
    "Не похоже на номер телефона. Пример: <code>+7 900 000 00 00</code>\n"
    "Или нажмите кнопку «Отправить телефон»."
)
ERR_CITY = "Название города — от 2 до 60 символов."
ERR_ADDRESS = "Адрес слишком короткий. Укажите улицу, дом и квартиру."
ERR_COMMENT = "Комментарий длиннее 500 символов — сократите, пожалуйста."
ERR_TEXT_EXPECTED = "Здесь нужен текст. Напишите ответ сообщением."

CHECKOUT_CANCELLED = "Оформление отменено. Корзина сохранена."
CART_CHANGED_ON_CONFIRM = (
    "🔄 Корзина изменилась, пока вы оформляли заказ.\n"
    "Проверьте состав и сумму ещё раз — заказ пока не создан."
)
CART_EMPTY_ON_CHECKOUT = (
    "Корзина опустела, пока вы оформляли заказ. Соберите кресло заново."
)


def confirm(customer: dict[str, str], items_text: str, total: int) -> str:
    comment = customer.get("comment", "")
    lines = [
        "🔍 <b>Проверьте заказ</b>",
        "",
        items_text,
        SEP,
        f"Итого: <b>{format_price(total)}</b>",
        "",
        f"👤 {esc(customer['name'])}",
        f"📞 {esc(customer['phone'])}",
        f"🏙 {esc(customer['city'])}",
        f"🏠 {esc(customer['address'])}",
    ]
    if comment:
        lines.append(f"💬 {esc(comment)}")
    lines += ["", "Всё верно?"]
    return "\n".join(lines)


def order_created(order_id: int, total: int, lead_days: int) -> str:
    return (
        f"🎉 <b>Заказ №{order_id} принят!</b>\n\n"
        f"Сумма: <b>{format_price(total)}</b>\n"
        f"Ориентировочная готовность: <b>{ready_date(lead_days)}</b>\n\n"
        "Менеджер свяжется с вами в течение рабочего дня, чтобы подтвердить "
        "детали и рассчитать доставку.\n\n"
        "Статус заказа всегда виден в разделе <b>«Мои заказы»</b>."
    )


# ----------------------------------------------------------------- мои заказы

ORDERS_EMPTY = (
    "📦 <b>Заказов пока нет</b>\n\n"
    "Соберите кресло и оформите первый заказ."
)


def order_short(order: Order) -> str:
    items = "\n".join(
        f"• {esc(item.product_name)} — <i>{esc(item.config_text)}</i> × {item.qty}"
        for item in order.items
    )
    return (
        f"<b>Заказ №{order.id}</b> от {format_dt(order.created_at)}\n"
        f"{items}\n"
        f"Сумма: <b>{format_price(order.total)}</b>\n"
        f"Статус: <b>{esc(order.status_label)}</b>"
    )


MESSAGE_LIMIT = 4096


def orders_list(orders: list[Order]) -> str:
    """История заказов, обрезанная по лимиту сообщения Telegram.

    Десять заказов по шесть позиций дают 4600 знаков — сообщение просто не
    уходит, и клиент не видит историю вообще. Лучше показать свежие и честно
    сказать, что остальные скрыты.
    """
    header = "📦 <b>Мои заказы</b>\n\n"
    divider = f"\n\n{SEP}\n\n"
    note = "\n\n<i>Показаны последние заказы. Остальные — у менеджера.</i>"

    blocks: list[str] = []
    length = len(header)
    for order in orders:
        block = order_short(order)
        addition = len(block) + (len(divider) if blocks else 0)
        if length + addition + len(note) > MESSAGE_LIMIT:
            return header + divider.join(blocks) + note
        blocks.append(block)
        length += addition
    return header + divider.join(blocks)


def status_changed(order: Order) -> str:
    return (
        f"🔔 Заказ <b>№{order.id}</b> — новый статус:\n"
        f"<b>{esc(order.status_label)}</b>"
    )


# ---------------------------------------------------------------------- админ

ADMIN_DENIED = "Раздел доступен только администратору."


def admin_new_order(order: Order) -> str:
    items = "\n".join(
        f"• {esc(item.product_name)} — <i>{esc(item.config_text)}</i>\n"
        f"  {item.qty} × {format_price(item.unit_price)}"
        for item in order.items
    )
    user = f"@{esc(order.username)}" if order.username else f"id {order.user_id}"
    comment = f"\n💬 {esc(order.comment)}" if order.comment else ""
    return (
        f"🔔 <b>НОВЫЙ ЗАКАЗ №{order.id}</b>\n"
        f"{format_dt(order.created_at)}\n\n"
        f"{items}\n\n"
        f"{SEP}\n"
        f"Сумма: <b>{format_price(order.total)}</b>\n\n"
        f"👤 {esc(order.customer_name)} ({user})\n"
        f"📞 <code>{esc(order.phone)}</code>\n"
        f"🏙 {esc(order.city)}\n"
        f"🏠 {esc(order.address)}"
        f"{comment}"
    )


def admin_panel(data: dict[str, int]) -> str:
    return (
        "🛠 <b>Панель администратора</b>\n\n"
        f"🆕 Новых заказов: <b>{data['new']}</b>\n"
        f"📦 Всего заказов: <b>{data['orders']}</b>\n"
        f"💰 Выручка: <b>{format_price(data['revenue'])}</b>\n"
        f"👥 Пользователей: <b>{data['users']}</b>\n"
        f"🛒 Корзин с товаром: <b>{data['active_carts']}</b>"
    )


def admin_order(order: Order) -> str:
    items = "\n".join(
        f"• {esc(item.product_name)} — <i>{esc(item.config_text)}</i>\n"
        f"  {item.qty} × {format_price(item.unit_price)} = {format_price(item.total)}"
        for item in order.items
    )
    user = f"@{esc(order.username)}" if order.username else f"id {order.user_id}"
    comment = f"\n💬 {esc(order.comment)}" if order.comment else ""
    return (
        f"📄 <b>Заказ №{order.id}</b>\n"
        f"Создан: {format_dt(order.created_at)}\n"
        f"Обновлён: {format_dt(order.updated_at)}\n"
        f"Статус: <b>{esc(order.status_label)}</b>\n\n"
        f"{items}\n\n"
        f"{SEP}\n"
        f"Сумма: <b>{format_price(order.total)}</b>\n\n"
        f"👤 {esc(order.customer_name)} ({user})\n"
        f"📞 <code>{esc(order.phone)}</code>\n"
        f"🏙 {esc(order.city)}\n"
        f"🏠 {esc(order.address)}"
        f"{comment}"
    )


ADMIN_NO_ORDERS = "Заказов пока нет."
ADMIN_EXPORT_EMPTY = "Выгружать нечего — заказов нет."
ADMIN_EXPORT_CAPTION = "📊 Выгрузка заказов"


def admin_status_set(order: Order) -> str:
    return f"Статус заказа №{order.id}: {order.status_label}"


ADMIN_STATUS_SAME = "Этот статус уже установлен."
ADMIN_NOTIFY_FAILED = "⚠️ Клиенту не удалось отправить уведомление (бот заблокирован)."


# ---------------------------------------------------------------------- ошибки

ERR_STALE = "Это сообщение устарело. Откройте раздел заново: /start"
