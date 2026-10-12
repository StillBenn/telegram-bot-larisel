"""Настройки бота.

Все значения читаются из .env — в исходном коде нет ни одного секрета.
Это позволяет отдавать репозиторий клиенту как есть.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


class ConfigError(RuntimeError):
    """Ошибка настройки — её показываем пользователю текстом, без стектрейса."""

load_dotenv(BASE_DIR / ".env")


def _parse_admin_ids(raw: str) -> tuple[int, ...]:
    """'123, 456; 789' -> (123, 456, 789). Пустая строка -> ()."""
    ids: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not chunk.lstrip("-").isdigit():
            raise ConfigError(
                f"ADMIN_IDS: «{chunk}» не является числовым Telegram ID. "
                "Узнать свой ID можно у бота @userinfobot."
            )
        ids.append(int(chunk))
    return tuple(dict.fromkeys(ids))  # порядок сохраняем, дубли убираем


@dataclass(frozen=True, slots=True)
class Settings:
    token: str
    admin_ids: tuple[int, ...]
    viewer_url: str
    manager_url: str
    shop_name: str
    db_path: Path
    assets_dir: Path

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "BOT_TOKEN не задан.\n"
            "1) Скопируйте .env.example в .env\n"
            "2) Получите токен у @BotFather и вставьте его в BOT_TOKEN"
        )

    data_dir = BASE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        token=token,
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        viewer_url=os.getenv(
            "VIEWER_URL", "https://stillbenn.github.io/threejs-chair-configurator/"
        ).strip(),
        manager_url=os.getenv("MANAGER_URL", "https://t.me/Still_Benn").strip(),
        shop_name=os.getenv("SHOP_NAME", "Мебельная мастерская Larisel").strip(),
        db_path=data_dir / os.getenv("DB_NAME", "larisel.sqlite3").strip(),
        assets_dir=BASE_DIR / "assets",
    )
