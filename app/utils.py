"""Мелкие помощники: формат цены, телефон, склонение слов, срок изготовления."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

NBSP = "\u00a0"

# \u041c\u0430\u0441\u0442\u0435\u0440\u0441\u043a\u0430\u044f \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442 \u043f\u043e \u041c\u043e\u0441\u043a\u0432\u0435, \u0430 VPS \u043f\u043e\u0447\u0442\u0438 \u0432\u0441\u0435\u0433\u0434\u0430 \u0432 UTC. \u0411\u0435\u0437 \u044f\u0432\u043d\u043e\u0439 \u0437\u043e\u043d\u044b
# \u0437\u0430\u043a\u0430\u0437, \u043e\u0444\u043e\u0440\u043c\u043b\u0435\u043d\u043d\u044b\u0439 \u0432 01:00 \u043c\u0441\u043a, \u043f\u043e\u043f\u0430\u0434\u0451\u0442 \u0432 \u0431\u0430\u0437\u0443 \u0438 \u0432 Excel \u0432\u0447\u0435\u0440\u0430\u0448\u043d\u0438\u043c \u0434\u043d\u0451\u043c,
# \u0430 \u0434\u0430\u0442\u0430 \u0433\u043e\u0442\u043e\u0432\u043d\u043e\u0441\u0442\u0438 \u0441\u0434\u0432\u0438\u043d\u0435\u0442\u0441\u044f \u043d\u0430 \u0441\u0443\u0442\u043a\u0438.
#
# Фиксированный сдвиг, а не ZoneInfo("Europe/Moscow"): Россия не переводит часы
# с 2014 года, поэтому UTC+3 верен круглый год — и не нужен пакет tzdata,
# которого в стандартной поставке Windows нет.
SHOP_TZ = timezone(timedelta(hours=3), "MSK")


def now() -> datetime:
    return datetime.now(SHOP_TZ)

# Телефон принимаем в любом человеческом виде и приводим к +7XXXXXXXXXX.
_PHONE_CLEAN_RE = re.compile(r"[^\d+]")


def format_price(value: int) -> str:
    """42900 -> '42 900 ₽' (неразрывные пробелы, чтобы цена не переносилась)."""
    return f"{value:,}".replace(",", NBSP) + f"{NBSP}₽"


def normalize_phone(raw: str) -> str | None:
    """Возвращает +7XXXXXXXXXX или None, если это не похоже на телефон.

    Принимаем и российские (11 цифр), и международные номера (10-15 цифр по E.164),
    потому что заказчик может писать из-за рубежа.
    """
    cleaned = _PHONE_CLEAN_RE.sub("", raw or "")
    if not cleaned:
        return None

    plus = cleaned.startswith("+")
    digits = cleaned.lstrip("+").replace("+", "")
    if not digits.isdigit():
        return None

    # 8XXXXXXXXXX и 7XXXXXXXXXX -> один формат
    if len(digits) == 11 and digits[0] in {"7", "8"}:
        return "+7" + digits[1:]
    if len(digits) == 10 and not plus:
        return "+7" + digits
    if 10 <= len(digits) <= 15:
        return "+" + digits
    return None


def plural(number: int, one: str, few: str, many: str) -> str:
    """Русское склонение: 1 день, 2 дня, 5 дней."""
    n = abs(number) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def lead_time_text(days: int) -> str:
    return f"{days} {plural(days, 'день', 'дня', 'дней')}"


def ready_date(days: int, today: date | None = None) -> str:
    """Ориентировочная дата готовности — клиенту это понятнее, чем «14 дней»."""
    base = today or now().date()
    return (base + timedelta(days=days)).strftime("%d.%m.%Y")


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def format_dt(iso: str) -> str:
    """ISO из базы -> '10.09.2026 18:42'. Битую строку возвращаем как есть."""
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return iso or "—"
