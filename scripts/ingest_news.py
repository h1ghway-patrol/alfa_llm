import argparse
import logging

from app.db.connection import connect, default_db_path, init_db
from app.ml.pipeline import process_news_folder


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--db", default=default_db_path())
    ap.add_argument("--llm", action="store_true", help="размечать через LLM (иначе запасной режим)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    conn = connect(args.db)
    init_db(conn)
    llm = None
    if args.llm:
        from app.ml.llm.client import LLMClient
        llm = LLMClient(conn)
    print(process_news_folder(conn, llm, args.folder))


if __name__ == "__main__":
    main()
