from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from app.db.connection import connect, default_db_path, init_db
from app.db.load_clients import load_clients
from app.db.load_counterparties import load_counterparties
from app.db.load_payments import load_payments
from app.db.passwords import hash_password
from app.db.repositories import create_user

log = logging.getLogger("build")


def _password_for(username: str) -> str:
    upper = username.upper()
    for name in (f"{upper}_PASSWORD", f"SEED_{upper}_PASSWORD"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return f"{username}-demo"


def seed_users(conn) -> None:
    for username, role in (("viewer", "viewer"), ("admin", "admin")):
        h, salt = hash_password(_password_for(username))
        create_user(conn, username, h, salt, role)
    log.warning("Созданы тестовые учётки viewer/admin. Для боевого запуска задайте VIEWER_PASSWORD и ADMIN_PASSWORD.")


def build(db_path: str, clients_csv: str | None = None, payments_path: str | None = None,
          all_clients: bool = False, rebuild: bool = False, counterparties_path: str | None = None) -> None:
    if rebuild and db_path != ":memory:":
        for suffix in ("", "-wal", "-shm"):
            Path(db_path + suffix).unlink(missing_ok=True)
    conn = connect(db_path)
    try:
        init_db(conn)
        if clients_csv:
            load_clients(conn, clients_csv, only_large=not all_clients)
        if payments_path:
            load_payments(conn, payments_path)
        if counterparties_path:
            load_counterparties(conn, counterparties_path)
        seed_users(conn)
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=default_db_path())
    ap.add_argument("--clients", help="путь к df_Uid_data_hack.csv")
    ap.add_argument("--payments", help="путь к df_Uid_payment_hack_2.csv.gz")
    ap.add_argument("--counterparties", help="путь к CSV контрагентов (SYNTHETIC_F, CITY_NAME, RC_NAME, SYNTHETIC_U)")
    ap.add_argument("--all-clients", action="store_true", help="грузить всех, а не только крупных")
    ap.add_argument("--rebuild", action="store_true", help="удалить БД и собрать с нуля")
    args = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    build(args.db, args.clients, args.payments, args.all_clients, args.rebuild, args.counterparties)
    log.info("Готово: %s", args.db)


if __name__ == "__main__":
    main()
