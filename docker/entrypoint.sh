#!/bin/sh
set -eu

DB_PATH="${DB_PATH:-/app/data/app.db}"
SEED_DIR="${SEED_DIR:-/seed}"
DEMO_DIR="/app/tests/data"
TMP_DB="${DB_PATH}.building"

build_db() {
    set -- python -m app.db.build --db "$TMP_DB"

    if [ -f "$SEED_DIR/df_Uid_data_hack.csv" ]; then
        echo "Собираю БД из выгрузок в ${SEED_DIR}"
        set -- "$@" --clients "$SEED_DIR/df_Uid_data_hack.csv"
        if [ -f "$SEED_DIR/df_Uid_payment_hack.csv" ]; then
            set -- "$@" --payments "$SEED_DIR/df_Uid_payment_hack.csv"
        fi
        if [ -f "$SEED_DIR/df_Fid_Uid_link_hack.csv" ]; then
            set -- "$@" --counterparties "$SEED_DIR/df_Fid_Uid_link_hack.csv"
        fi
        if [ "${LOAD_ALL_CLIENTS:-false}" = "true" ]; then
            set -- "$@" --all-clients
        fi
    else
        echo "Выгрузки не найдены в ${SEED_DIR}: собираю демо-БД"
        set -- "$@" --clients "$DEMO_DIR/clients_sample.csv"
    fi

    "$@"

    DOCS_DIR="$SEED_DIR/bank"
    [ -d "$DOCS_DIR" ] || DOCS_DIR="$DEMO_DIR/bank"
    NEWS_DIR="$SEED_DIR/news"
    [ -d "$NEWS_DIR" ] || NEWS_DIR="$DEMO_DIR/news"

    if [ -d "$DOCS_DIR" ]; then
        python -m scripts.ingest_docs "$DOCS_DIR" --db "$TMP_DB"
    fi
    if [ -d "$NEWS_DIR" ]; then
        python -m scripts.ingest_news "$NEWS_DIR" --db "$TMP_DB"
    fi
}

mkdir -p "$(dirname "$DB_PATH")"

if [ "${REBUILD_DB:-false}" = "true" ]; then
    echo "REBUILD_DB=true: удаляю ${DB_PATH}"
    rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"
fi

if [ ! -f "$DB_PATH" ]; then
    rm -f "$TMP_DB" "$TMP_DB-wal" "$TMP_DB-shm"
    build_db
    mv "$TMP_DB" "$DB_PATH"
    rm -f "$TMP_DB-wal" "$TMP_DB-shm"
    echo "БД готова: ${DB_PATH}"
fi

exec "$@"
