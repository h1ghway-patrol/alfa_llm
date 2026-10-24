"""Сборка `app/fixtures/clients.json` из реальной выгрузки клиентов.

Читает `data/df_Uid_data_hack.csv` и `data/df_Uid_payment_hack.csv`, повторяет
правила DB-2/DB-3 (дубли, флаги, корзины выручки, продукты, группы, платежи)
и пишет фикстуру теми же полями, что отдаёт `ClientProfile`.

Запуск: `python -m scripts.build_clients_fixture`
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIENTS_CSV = ROOT / "data" / "df_Uid_data_hack.csv"
PAYMENTS_CSV = ROOT / "data" / "df_Uid_payment_hack.csv"
OUTPUT = ROOT / "app" / "fixtures" / "clients.json"

DEMO_CLIENTS = ("U_1465", "U_51606", "U_57706")
LARGE_REVENUE = 15_000_000_000

PRODUCT_FLAGS = {
    "CL_PRODUCT_RKO_MARK": "rko",
    "CL_PRODUCT_GAR_MARK": "guarantee",
    "CL_PRODUCT_LOA_MARK": "loan",
    "CL_PRODUCT_LEA_MARK": "leasing",
    "CL_PRODUCT_DEP_MARK": "deposit",
    "CL_PRODUCT_ZPP_MARK": "payroll",
    "FACTORING_MARK": "factoring",
}

PRODUCT_LABELS = {
    "rko": "РКО",
    "guarantee": "гарантия",
    "loan": "кредит",
    "leasing": "лизинг",
    "deposit": "депозит",
    "payroll": "зарплатный проект",
    "factoring": "факторинг",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def is_set(value: str | None) -> bool:
    return (value or "").strip() in {"1", "1.0", "true", "True"}


def revenue_band(revenue: float) -> str:
    if revenue <= 15_000_000_000:
        return "менее 15 млрд ₽"
    if revenue <= 50_000_000_000:
        return "15-50 млрд ₽"
    if revenue <= 105_000_000_000:
        return "50-105 млрд ₽"
    return "более 105 млрд ₽"


def clean_city(city: str) -> str:
    return city.removeprefix("г. ").strip()


def clean_ownership(value: str) -> str:
    return value.strip().capitalize()


def split_countries(value: str) -> list[str]:
    return [part.strip().capitalize() for part in value.split(",") if part.strip()]


def payment_counts(path: Path) -> dict[str, dict[str, int]]:
    incoming: dict[str, set[str]] = {client_id: set() for client_id in DEMO_CLIENTS}
    outgoing: dict[str, set[str]] = {client_id: set() for client_id in DEMO_CLIENTS}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            payer = row["PAYER"].strip()
            beneficiary = row["BENEFICIARY"].strip()
            if not payer or payer == beneficiary:
                continue
            if beneficiary in incoming:
                incoming[beneficiary].add(payer)
            if payer in outgoing:
                outgoing[payer].add(beneficiary)
    return {
        client_id: {
            "incoming_partners": len(incoming[client_id]),
            "outgoing_partners": len(outgoing[client_id]),
        }
        for client_id in DEMO_CLIENTS
    }


def build_tags(profile: dict[str, object]) -> list[dict[str, object]]:
    tags: list[dict[str, object]] = []

    okved_code = profile["okved_code"]
    okved_name = profile["okved_name"]
    if okved_code and okved_name:
        tags.append(
            {
                "code": "industry",
                "label": str(okved_name),
                "evidence": [f"ОКВЭД {okved_code} — {okved_name}"],
            }
        )

    products = profile["products"]
    debt_products = [p for p in products if p in {"loan", "leasing", "guarantee"}]
    if debt_products:
        labels = ", ".join(PRODUCT_LABELS[p] for p in debt_products)
        tags.append(
            {
                "code": "debt_sensitivity",
                "label": f"Чувствителен к ставке: {labels}",
                "evidence": [f"Продукт банка: {PRODUCT_LABELS[p]}" for p in debt_products],
            }
        )

    countries = profile["fts_countries"]
    if countries:
        tags.append(
            {
                "code": "currency_dependency",
                "label": "Зависит от курса: работает с ВЭД",
                "evidence": ["Внешнеторговые операции: " + ", ".join(countries)],
            }
        )

    if profile["group_size"] and int(profile["group_size"]) > 1:
        tags.append(
            {
                "code": "group_position",
                "label": f"Входит в группу из {profile['group_size']} крупных клиентов",
                "evidence": [f"Группа {profile['group_id']}"],
            }
        )

    if profile["is_large"]:
        tags.append(
            {
                "code": "scale",
                "label": "Крупный бизнес",
                "evidence": [f"Выручка {profile['revenue_band']}"],
            }
        )

    return tags


def main() -> int:
    rows = read_rows(CLIENTS_CSV)
    id_counts = Counter(row["SYNTHETIC_U"] for row in rows)
    duplicates = {client_id for client_id, count in id_counts.items() if count > 1}
    clean_rows = [row for row in rows if row["SYNTHETIC_U"] not in duplicates]

    large_by_group = Counter(
        row["GROUP_ID"]
        for row in clean_rows
        if float(row["REVENUE_COMPANY"] or 0) > LARGE_REVENUE
    )
    by_id = {row["SYNTHETIC_U"]: row for row in clean_rows}
    payments = payment_counts(PAYMENTS_CSV)

    missing = [client_id for client_id in DEMO_CLIENTS if client_id not in by_id]
    if missing:
        print(f"Нет демо-клиентов в выгрузке: {', '.join(missing)}", file=sys.stderr)
        return 1

    profiles: list[dict[str, object]] = []
    for client_id in DEMO_CLIENTS:
        row = by_id[client_id]
        revenue = float(row["REVENUE_COMPANY"] or 0)
        products = [
            product for flag, product in PRODUCT_FLAGS.items() if is_set(row.get(flag))
        ]
        group_id = row["GROUP_ID"].strip() or None
        profile: dict[str, object] = {
            "client_id": client_id,
            "okved_code": row["MAINOKVED_CODE"].strip() or None,
            "okved_name": row["MAINOKVED_NAME"].strip() or None,
            "city": clean_city(row["CITY"]),
            "region": row["REGION"].strip() or None,
            "revenue_rub": revenue,
            "revenue_band": revenue_band(revenue),
            "employees_band": row["AMOUNT_WORKERS_FNS_GRADATION"].strip() or None,
            "age_band": row["COMPANY_AGE_YEARS_GRADATION"].strip() or None,
            "ownership": clean_ownership(row["OKFS_NAME"]),
            "client_type": row["CL_TYPE"].strip() or None,
            "products": products,
            "fts_countries": split_countries(row["FTS_COUNTRY_NAME"]),
            "group_id": group_id,
            "group_size": large_by_group.get(group_id, 0) if group_id else None,
            "is_large": revenue > LARGE_REVENUE,
            "is_demo": True,
            "payments": payments[client_id],
            "tags": [],
        }
        profile["tags"] = build_tags(profile)
        profiles.append(profile)

    OUTPUT.write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Записано {len(profiles)} клиентов в {OUTPUT.relative_to(ROOT)}; "
        f"строк в выгрузке {len(rows)}, удалено дублей {len(rows) - len(clean_rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
