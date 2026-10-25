"""Схемы клиента: краткая карточка для списка и полный профиль с бизнес-контекстом."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Id

ProductCode = Literal[
    "loan",
    "leasing",
    "guarantee",
    "deposit",
    "rko",
    "payroll",
    "factoring",
]
"""Продукт банка, которым пользуется клиент."""

IndustryTagCode = Literal[
    "industry",
    "debt_sensitivity",
    "currency_dependency",
    "group_position",
    "scale",
]
"""Код бизнес-тега профиля: отрасль, чувствительность к долгу, валютная зависимость, положение в группе, масштаб."""

ClientType = Literal["CLIENT", "PROSPECT", "CLOSE_CLIENT"]
"""Тип клиента из исходного CSV (`CL_TYPE`)."""


class ClientTag(BaseModel):
    """Бизнес-тег профиля с признаками, которые его породили."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "code": "debt_sensitivity",
                    "label": "Чувствителен к ставке: есть кредит и лизинг",
                    "evidence": ["Кредит в портфеле банка", "Договор лизинга"],
                }
            ]
        }
    )

    code: IndustryTagCode = Field(description="Машинный код тега.")
    label: str = Field(
        description="Человекочитаемая формулировка тега на русском, готовая к показу.",
        examples=["Чувствителен к ставке: есть кредит и лизинг"],
    )
    evidence: list[str] = Field(
        description="Признаки клиента, из которых получен тег. Пустой список означает, что признак не подтверждён.",
    )


class ClientSummary(BaseModel):
    """Карточка клиента для списка `GET /clients`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "client_id": "U_1465",
                    "okved_code": "46.32",
                    "okved_name": "Оптовая торговля пищевыми продуктами",
                    "city": "Москва",
                    "region": "Москва",
                    "revenue_band": "15-50 млрд ₽",
                    "products": ["loan", "leasing"],
                    "group_id": "group_1032_sb",
                    "group_size": 3,
                    "is_large": True,
                    "is_demo": True,
                }
            ]
        }
    )

    client_id: Id = Field(description="Идентификатор клиента.")
    okved_code: str | None = Field(default=None, description="Код ОКВЭД, например `46.32`.")
    okved_name: str | None = Field(default=None, description="Название отрасли по ОКВЭД.")
    city: str | None = Field(default=None, description="Город.")
    region: str | None = Field(default=None, description="Регион.")
    revenue_band: str | None = Field(default=None, description="Корзина выручки, например `15-50 млрд ₽`.")
    products: list[ProductCode] = Field(
        description="Продукты банка, которыми пользуется клиент.",
    )
    group_id: str | None = Field(default=None, description="Идентификатор группы компаний, если клиент входит в группу.")
    group_size: int | None = Field(default=None, description="Сколько крупных клиентов в группе.")
    is_large: bool = Field(description="Крупный бизнес: выручка больше 15 млрд ₽.")
    is_demo: bool = Field(description="Клиент из демонстрационной выборки.")


class ClientPayments(BaseModel):
    """Граф платежей: вспомогательный признак, а не основной."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"incoming_partners": 1230, "outgoing_partners": 210}]
        }
    )

    incoming_partners: int = Field(ge=0, description="Сколько компаний платит клиенту.")
    outgoing_partners: int = Field(ge=0, description="Сколько компаний получает оплату от клиента.")


class CounterpartyLink(BaseModel):
    """Крупнейший контрагент клиента в графе платежей."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "counterparty_id": "F_2",
                    "amount_rub": 750000000.0,
                    "operations": 12,
                    "city": "Казань",
                    "region": "Татарстан",
                }
            ]
        }
    )

    counterparty_id: Id = Field(description="Идентификатор контрагента в выгрузке.")
    amount_rub: float = Field(ge=0, description="Суммарный оборот с контрагентом, ₽.")
    operations: int = Field(ge=0, description="Количество платежей с контрагентом.")
    city: str | None = Field(default=None, description="Город контрагента, если известен.")
    region: str | None = Field(default=None, description="Регион контрагента, если известен.")


class ClientGeography(BaseModel):
    """География контрагентов клиента."""

    cities: list[str] = Field(description="Города контрагентов без повторов.")
    regions: list[str] = Field(description="Регионы контрагентов без повторов.")


class ClientConnections(BaseModel):
    """Связи клиента: крупнейшие входящие и исходящие платежи плюс география."""

    top_outgoing: list[CounterpartyLink] = Field(description="Крупнейшие получатели платежей клиента.")
    top_incoming: list[CounterpartyLink] = Field(description="Крупнейшие плательщики клиенту.")
    geography: ClientGeography = Field(description="География контрагентов из выгрузки.")


class ClientProfile(BaseModel):
    """Полный профиль клиента: `GET /clients/{client_id}/profile`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "client_id": "U_1465",
                    "okved_code": "46.32",
                    "okved_name": "Оптовая торговля пищевыми продуктами",
                    "city": "Москва",
                    "region": "Москва",
                    "revenue_rub": 44400000000.0,
                    "revenue_band": "15-50 млрд ₽",
                    "employees_band": "более 250",
                    "age_band": "более 10 лет",
                    "ownership": "Частная",
                    "client_type": "CLIENT",
                    "products": ["loan", "leasing"],
                    "fts_countries": ["Грузия", "Азербайджан", "Туркмения"],
                    "group_id": "group_1032_sb",
                    "group_size": 3,
                    "is_large": True,
                    "is_demo": True,
                    "payments": {"incoming_partners": 1230, "outgoing_partners": 210},
                    "connections": {
                        "top_outgoing": [
                            {
                                "counterparty_id": "F_2",
                                "amount_rub": 750000000.0,
                                "operations": 12,
                                "city": "Казань",
                                "region": "Татарстан",
                            }
                        ],
                        "top_incoming": [
                            {
                                "counterparty_id": "F_1",
                                "amount_rub": 1000000000.0,
                                "operations": 7,
                                "city": "Москва",
                                "region": "Московская область",
                            }
                        ],
                        "geography": {"cities": ["Казань", "Москва"], "regions": ["Московская область", "Татарстан"]},
                    },
                    "tags": [
                        {
                            "code": "debt_sensitivity",
                            "label": "Чувствителен к ставке: есть кредит и лизинг",
                            "evidence": ["Кредит в портфеле банка", "Договор лизинга"],
                        },
                        {
                            "code": "currency_dependency",
                            "label": "Зависит от курса: работает с ВЭД",
                            "evidence": ["ВЭД с Грузией, Азербайджаном и Туркменией"],
                        },
                    ],
                }
            ]
        }
    )

    client_id: Id = Field(description="Идентификатор клиента.")
    okved_code: str | None = Field(default=None, description="Код ОКВЭД, например `46.32`.")
    okved_name: str | None = Field(default=None, description="Название отрасли по ОКВЭД.")
    city: str | None = Field(default=None, description="Город.")
    region: str | None = Field(default=None, description="Регион.")
    revenue_rub: float | None = Field(default=None, description="Выручка в рублях.")
    revenue_band: str | None = Field(default=None, description="Корзина выручки, например `15-50 млрд ₽`.")
    employees_band: str | None = Field(default=None, description="Корзина по числу сотрудников.")
    age_band: str | None = Field(default=None, description="Корзина по возрасту клиента.")
    ownership: str | None = Field(default=None, description="Форма собственности.")
    client_type: ClientType | None = Field(default=None, description="Тип клиента из исходных данных (`CL_TYPE`).")
    products: list[ProductCode] = Field(description="Продукты банка, которыми пользуется клиент.")
    fts_countries: list[str] = Field(
        description="Страны внешнеторговых операций. Пустой список означает, что ВЭД не подтверждена.",
    )
    group_id: str | None = Field(default=None, description="Идентификатор группы компаний, если клиент входит в группу.")
    group_size: int | None = Field(default=None, description="Сколько крупных клиентов в группе.")
    is_large: bool = Field(description="Крупный бизнес: выручка больше 15 млрд ₽.")
    is_demo: bool = Field(description="Клиент из демонстрационной выборки.")
    payments: ClientPayments | None = Field(
        default=None,
        description="Граф платежей. Может отсутствовать, если платежи для клиента не считались.",
    )
    connections: ClientConnections | None = Field(
        default=None,
        description="Крупнейшие контрагенты и география связей. Может отсутствовать в режиме фикстур.",
    )
    tags: list[ClientTag] = Field(description="Бизнес-теги профиля с признаками, которые их породили.")
