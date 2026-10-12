"""Каталог и расчёт цены.

ВАЖНО: цены и названия опций совпадают один в один с 3D-конфигуратором
(https://stillbenn.github.io/threejs-chair-configurator/). Клиент видит в боте
ту же цену, что и в 3D — иначе доверие теряется на первом же заказе.

Чтобы добавить опцию или товар, меняется ТОЛЬКО этот файл: клавиатуры,
тексты и расчёт строятся из данных ниже автоматически.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Option:
    id: str
    name: str
    price: int          # надбавка к базовой цене, ₽
    emoji: str = ""
    note: str = ""      # уточнение под названием (например, габариты)


@dataclass(frozen=True, slots=True)
class OptionGroup:
    id: str
    title: str
    emoji: str
    options: tuple[Option, ...]
    hint: str = ""

    @property
    def default(self) -> Option:
        return self.options[0]

    def get(self, option_id: str | None) -> Option:
        """Опция по id. Неизвестный id -> значение по умолчанию.

        Так конфигурация из старой версии бота не «ломает» пользователю корзину.
        """
        for option in self.options:
            if option.id == option_id:
                return option
        return self.default


FABRIC = OptionGroup(
    id="fabric",
    title="Ткань",
    emoji="🎨",
    hint="Износостойкий велюр, 100 000 циклов по Мартиндейлу.",
    options=(
        Option("sand", "Песочный", 0, "🟨"),
        Option("cream", "Сливочный", 0, "⬜"),
        Option("graphite", "Графит", 2400, "⬛"),
        Option("olive", "Олива", 2400, "🟩"),
        Option("terracotta", "Терракота", 3200, "🟧"),
        Option("indigo", "Индиго", 3200, "🟦"),
    ),
)

FRAME = OptionGroup(
    id="frame",
    title="Каркас",
    emoji="🪵",
    hint="Массив или металл с порошковой окраской.",
    options=(
        Option("oak", "Дуб", 0, "🟫"),
        Option("walnut", "Орех", 3600, "🟤"),
        Option("black", "Чёрный металл", 5200, "⬛"),
        Option("brass", "Латунь", 8900, "🟡"),
    ),
)

SIZE = OptionGroup(
    id="size",
    title="Размер",
    emoji="📐",
    options=(
        Option("std", "Стандарт", 0, "📏", "Ш 78 × Г 82 × В 74 см"),
        Option("xl", "XL", 7400, "📏", "Ш 92 × Г 88 × В 78 см"),
    ),
)

PILLOW = OptionGroup(
    id="pillow",
    title="Подушка",
    emoji="🛋",
    hint="Декоративная подушка в тон или контраст.",
    options=(
        Option("no", "Без подушки", 0, "➖"),
        Option("yes", "С подушкой", 2900, "🛋"),
    ),
)


@dataclass(frozen=True, slots=True)
class Product:
    id: str
    name: str
    subtitle: str
    description: str
    base_price: int
    lead_days: int
    groups: tuple[OptionGroup, ...]
    photo: str = ""     # имя файла в assets/, пусто -> отправляем без фото

    def group(self, group_id: str) -> OptionGroup | None:
        for group in self.groups:
            if group.id == group_id:
                return group
        return None

    def default_config(self) -> dict[str, str]:
        return {group.id: group.default.id for group in self.groups}

    def normalize(self, config: dict[str, str] | None) -> dict[str, str]:
        """Приводит любую конфигурацию к валидной: лишнее убирает, недостающее дополняет."""
        config = config or {}
        return {group.id: group.get(config.get(group.id)).id for group in self.groups}

    def price(self, config: dict[str, str] | None) -> int:
        config = self.normalize(config)
        return self.base_price + sum(
            group.get(config[group.id]).price for group in self.groups
        )

    def selected(self, config: dict[str, str] | None) -> list[tuple[OptionGroup, Option]]:
        config = self.normalize(config)
        return [(group, group.get(config[group.id])) for group in self.groups]

    def config_line(self, config: dict[str, str] | None) -> str:
        """Однострочное описание сборки — для корзины, заказа и выгрузки."""
        return ", ".join(option.name for _, option in self.selected(config))


CHAIR_LARISEL = Product(
    id="chair-larisel",
    name="Кресло Larisel",
    subtitle="Каркас из массива, съёмные чехлы, ручная сборка",
    description=(
        "Кресло собирается под заказ: 6 тканей, 4 варианта каркаса, два размера "
        "и декоративная подушка. Чехлы съёмные — их можно стирать. "
        "Посадочная высота 46 см."
    ),
    base_price=42_900,
    lead_days=14,
    groups=(FABRIC, FRAME, SIZE, PILLOW),
    photo="chair-larisel.jpg",
)

PRODUCTS: tuple[Product, ...] = (CHAIR_LARISEL,)


def get_product(product_id: str) -> Product | None:
    for product in PRODUCTS:
        if product.id == product_id:
            return product
    return None
