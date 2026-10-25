import argparse
import logging

from app.db.connection import connect, default_db_path, init_db
from app.ml.ingest.bank_docs import ingest_docs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--db", default=default_db_path())
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    conn = connect(args.db)
    init_db(conn)
    print(ingest_docs(conn, args.folder))


if __name__ == "__main__":
    main()
