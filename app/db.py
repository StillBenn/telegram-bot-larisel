"""Слой данных: SQLite через стандартный sqlite3.

Почему не ORM и не aiosqlite: у бота три таблицы и десяток запросов —
внешняя зависимость здесь стоила бы дороже, чем экономила. Блокирующие вызовы
sqlite3 уводим в поток через asyncio.to_thread, поэтому event loop не встаёт.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .utils import now_iso

# --------------------------------------------------------------------- статусы

STATUS_NEW = "new"
STATUS_CONFIRMED = "confirmed"
STATUS_PRODUCTION = "production"
STATUS_SHIPPED = "shipped"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"

STATUSES: dict[str, str] = {
    STATUS_NEW: "🆕 Новый",
    STATUS_CONFIRMED: "✅ Подтверждён",
    STATUS_PRODUCTION: "🔨 В производстве",
    STATUS_SHIPPED: "🚚 Передан в доставку",
    STATUS_DONE: "🎉 Выполнен",
    STATUS_CANCELLED: "❌ Отменён",
}

# О смене статуса клиенту приходит уведомление — кроме момента создания заказа.
NOTIFY_STATUSES = frozenset(STATUSES) - {STATUS_NEW}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    created_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cart_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    product_id  TEXT    NOT NULL,
    config_json TEXT    NOT NULL,
    qty         INTEGER NOT NULL CHECK (qty > 0),
    unit_price  INTEGER NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cart_user ON cart_items (user_id);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    username      TEXT,
    customer_name TEXT    NOT NULL,
    phone         TEXT    NOT NULL,
    city          TEXT    NOT NULL,
    address       TEXT    NOT NULL,
    comment       TEXT,
    total         INTEGER NOT NULL,
    status        TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders (user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);

CREATE TABLE IF NOT EXISTS order_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     INTEGER NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    product_id   TEXT    NOT NULL,
    product_name TEXT    NOT NULL,
    config_text  TEXT    NOT NULL,
    config_json  TEXT    NOT NULL,
    qty          INTEGER NOT NULL,
    unit_price   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items (order_id);
"""

_db_path: Path | None = None


# ------------------------------------------------------------------ соединение

@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    if _db_path is None:
        raise RuntimeError("База не инициализирована: вызовите init_db() при старте.")
    conn = sqlite3.connect(_db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:            # commit при успехе, rollback при исключении
            yield conn
    finally:
        conn.close()


def _init_sync(path: Path) -> None:
    global _db_path
    _db_path = path
    conn = sqlite3.connect(path)
    try:
        # WAL: чтение не блокируется записью — важно, когда админ смотрит
        # заказы, а клиент в этот момент оформляет новый.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


async def init_db(path: Path) -> None:
    await asyncio.to_thread(_init_sync, path)


# ------------------------------------------------------------------- строки БД

@dataclass(frozen=True, slots=True)
class CartItem:
    id: int
    product_id: str
    config: dict[str, str]
    qty: int
    unit_price: int

    @property
    def total(self) -> int:
        return self.qty * self.unit_price


@dataclass(frozen=True, slots=True)
class OrderItem:
    product_name: str
    config_text: str
    qty: int
    unit_price: int

    @property
    def total(self) -> int:
        return self.qty * self.unit_price


@dataclass(frozen=True, slots=True)
class Order:
    id: int
    user_id: int
    username: str | None
    customer_name: str
    phone: str
    city: str
    address: str
    comment: str
    total: int
    status: str
    created_at: str
    updated_at: str
    items: tuple[OrderItem, ...] = ()

    @property
    def status_label(self) -> str:
        return STATUSES.get(self.status, self.status)


def _order_from_row(row: sqlite3.Row, items: tuple[OrderItem, ...] = ()) -> Order:
    return Order(
        id=row["id"],
        user_id=row["user_id"],
        username=row["username"],
        customer_name=row["customer_name"],
        phone=row["phone"],
        city=row["city"],
        address=row["address"],
        comment=row["comment"] or "",
        total=row["total"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        items=items,
    )


def _items_sync(conn: sqlite3.Connection, order_id: int) -> tuple[OrderItem, ...]:
    rows = conn.execute(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)
    ).fetchall()
    return tuple(
        OrderItem(
            product_name=row["product_name"],
            config_text=row["config_text"],
            qty=row["qty"],
            unit_price=row["unit_price"],
        )
        for row in rows
    )


# ----------------------------------------------------------------- пользователи

def _upsert_user_sync(user_id: int, username: str | None, full_name: str) -> None:
    stamp = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO users (id, username, full_name, created_at, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                username  = excluded.username,
                full_name = excluded.full_name,
                last_seen = excluded.last_seen
            """,
            (user_id, username, full_name, stamp, stamp),
        )


async def upsert_user(user_id: int, username: str | None, full_name: str) -> None:
    await asyncio.to_thread(_upsert_user_sync, user_id, username, full_name)


# --------------------------------------------------------------------- корзина

MAX_QTY = 20

# Каталог даёт 6×4×2×2 = 96 разных сборок, и каждая — отдельная строка корзины.
# Больше пятнадцати не помещается в одно сообщение Telegram, а корзина хранится
# в базе: переполнив её, клиент не смог бы открыть корзину уже никогда.
MAX_POSITIONS = 15


def _add_to_cart_sync(
    user_id: int, product_id: str, config: dict[str, str], unit_price: int
) -> bool:
    """Одинаковая сборка не плодит строки — растёт количество.

    False — достигнут предел числа разных сборок, ничего не добавлено.
    """
    config_json = json.dumps(config, sort_keys=True, ensure_ascii=False)
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, qty FROM cart_items
            WHERE user_id = ? AND product_id = ? AND config_json = ?
            """,
            (user_id, product_id, config_json),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE cart_items SET qty = ? WHERE id = ?",
                (min(row["qty"] + 1, MAX_QTY), row["id"]),
            )
            return True

        positions = conn.execute(
            "SELECT COUNT(*) AS n FROM cart_items WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]
        if positions >= MAX_POSITIONS:
            return False

        conn.execute(
            """
            INSERT INTO cart_items
                (user_id, product_id, config_json, qty, unit_price, created_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (user_id, product_id, config_json, unit_price, now_iso()),
        )
        return True


async def add_to_cart(
    user_id: int, product_id: str, config: dict[str, str], unit_price: int
) -> bool:
    return await asyncio.to_thread(
        _add_to_cart_sync, user_id, product_id, config, unit_price
    )


def _get_cart_sync(user_id: int) -> list[CartItem]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM cart_items WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
    return [
        CartItem(
            id=row["id"],
            product_id=row["product_id"],
            config=json.loads(row["config_json"]),
            qty=row["qty"],
            unit_price=row["unit_price"],
        )
        for row in rows
    ]


async def get_cart(user_id: int) -> list[CartItem]:
    return await asyncio.to_thread(_get_cart_sync, user_id)


def _change_qty_sync(user_id: int, item_id: int, delta: int) -> None:
    """Количество ниже 1 удаляет позицию, выше MAX_QTY не растёт."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT qty FROM cart_items WHERE id = ? AND user_id = ?",
            (item_id, user_id),
        ).fetchone()
        if row is None:
            return
        new_qty = row["qty"] + delta
        if new_qty < 1:
            conn.execute("DELETE FROM cart_items WHERE id = ?", (item_id,))
        else:
            conn.execute(
                "UPDATE cart_items SET qty = ? WHERE id = ?",
                (min(new_qty, MAX_QTY), item_id),
            )


async def change_qty(user_id: int, item_id: int, delta: int) -> None:
    await asyncio.to_thread(_change_qty_sync, user_id, item_id, delta)


def _remove_item_sync(user_id: int, item_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM cart_items WHERE id = ? AND user_id = ?", (item_id, user_id)
        )


async def remove_item(user_id: int, item_id: int) -> None:
    await asyncio.to_thread(_remove_item_sync, user_id, item_id)


def _clear_cart_sync(user_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))


async def clear_cart(user_id: int) -> None:
    await asyncio.to_thread(_clear_cart_sync, user_id)


# ---------------------------------------------------------------------- заказы

def _create_order_sync(
    user_id: int,
    username: str | None,
    customer: dict[str, str],
    items: list[tuple[str, str, str, dict[str, str], int, int]],
    total: int,
) -> int:
    """Создаёт заказ и очищает корзину одной транзакцией.

    Либо заказ создан и корзина пуста, либо не изменилось ничего — промежуточного
    состояния (заказ есть, корзина осталась) быть не может.
    """
    stamp = now_iso()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO orders (user_id, username, customer_name, phone, city,
                                address, comment, total, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                customer["name"],
                customer["phone"],
                customer["city"],
                customer["address"],
                customer.get("comment", ""),
                total,
                STATUS_NEW,
                stamp,
                stamp,
            ),
        )
        order_id = int(cursor.lastrowid)
        conn.executemany(
            """
            INSERT INTO order_items
                (order_id, product_id, product_name, config_text, config_json, qty, unit_price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    order_id,
                    product_id,
                    product_name,
                    config_text,
                    json.dumps(config, sort_keys=True, ensure_ascii=False),
                    qty,
                    unit_price,
                )
                for product_id, product_name, config_text, config, qty, unit_price in items
            ],
        )
        conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
    return order_id


async def create_order(
    user_id: int,
    username: str | None,
    customer: dict[str, str],
    items: list[tuple[str, str, str, dict[str, str], int, int]],
    total: int,
) -> int:
    return await asyncio.to_thread(
        _create_order_sync, user_id, username, customer, items, total
    )


def _get_order_sync(order_id: int) -> Order | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            return None
        return _order_from_row(row, _items_sync(conn, order_id))


async def get_order(order_id: int) -> Order | None:
    return await asyncio.to_thread(_get_order_sync, order_id)


def _user_orders_sync(user_id: int, limit: int) -> list[Order]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [_order_from_row(row, _items_sync(conn, row["id"])) for row in rows]


async def user_orders(user_id: int, limit: int = 10) -> list[Order]:
    return await asyncio.to_thread(_user_orders_sync, user_id, limit)


def _list_orders_sync(offset: int, limit: int, status: str | None) -> list[Order]:
    query = "SELECT * FROM orders"
    params: list[object] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [_order_from_row(row, _items_sync(conn, row["id"])) for row in rows]


async def list_orders(
    offset: int = 0, limit: int = 5, status: str | None = None
) -> list[Order]:
    return await asyncio.to_thread(_list_orders_sync, offset, limit, status)


def _count_orders_sync(status: str | None) -> int:
    with _connect() as conn:
        if status:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM orders WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()
    return int(row["n"])


async def count_orders(status: str | None = None) -> int:
    return await asyncio.to_thread(_count_orders_sync, status)


def _set_status_sync(order_id: int, status: str) -> bool:
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ? AND status != ?",
            (status, now_iso(), order_id, status),
        )
    return cursor.rowcount > 0


async def set_status(order_id: int, status: str) -> bool:
    """True, если статус действительно изменился (иначе клиенту не пишем)."""
    return await asyncio.to_thread(_set_status_sync, order_id, status)


# ------------------------------------------------------------------- статистика

def _stats_sync() -> dict[str, int]:
    with _connect() as conn:
        totals = conn.execute(
            """
            SELECT COUNT(*) AS orders,
                   COALESCE(SUM(total), 0) AS revenue
            FROM orders WHERE status != ?
            """,
            (STATUS_CANCELLED,),
        ).fetchone()
        new_count = conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE status = ?", (STATUS_NEW,)
        ).fetchone()
        users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        carts = conn.execute(
            "SELECT COUNT(DISTINCT user_id) AS n FROM cart_items"
        ).fetchone()
    return {
        "orders": int(totals["orders"]),
        "revenue": int(totals["revenue"]),
        "new": int(new_count["n"]),
        "users": int(users["n"]),
        "active_carts": int(carts["n"]),
    }


async def stats() -> dict[str, int]:
    return await asyncio.to_thread(_stats_sync)


def _export_rows_sync() -> list[dict[str, object]]:
    """Плоская таблица «одна строка = одна позиция заказа» — для Excel и CSV."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT o.id            AS order_id,
                   o.created_at    AS created_at,
                   o.status        AS status,
                   o.customer_name AS customer_name,
                   o.phone         AS phone,
                   o.city          AS city,
                   o.address       AS address,
                   o.comment       AS comment,
                   o.username      AS username,
                   o.user_id       AS user_id,
                   i.product_name  AS product_name,
                   i.config_text   AS config_text,
                   i.qty           AS qty,
                   i.unit_price    AS unit_price,
                   o.total         AS order_total
            FROM orders o
            LEFT JOIN order_items i ON i.order_id = o.id
            ORDER BY o.id DESC, i.id
            """
        ).fetchall()
    return [dict(row) for row in rows]


async def export_rows() -> list[dict[str, object]]:
    return await asyncio.to_thread(_export_rows_sync)
