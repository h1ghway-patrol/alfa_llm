# alfa_llm

Сервис персональной интерпретации новостей для клиентов банка: собирает
новости и документы банка, отбирает релевантные события, строит профиль
клиента и объясняет, как событие влияет на его бизнес.

В репозитории — API на FastAPI, SQLite-хранилище с полнотекстовым поиском,
ML-пайплайн ранжирования и агент генерации инсайтов, а также веб-интерфейс.

## Возможности

- персональная лента событий с оценкой релевантности и объяснением причин;
- профиль клиента: ОКВЭД, продукты, теги, платёжный граф, крупнейшие
  контрагенты и география связей;
- генерация структурированного инсайта: факты, последствия, рекомендации;
- ссылки на первоисточники и банковские документы;
- обратная связь по инсайтам;
- админка: добавление новостей, расход токенов, трасса шагов агента;
- два режима данных: демо-фикстуры и SQLite (`USE_DB=true`);
- провайдеры LLM: `fake` для локальной разработки и `remote` для реальной модели.

## Быстрый старт: Docker

Нужен Docker с Compose.

```bash
docker compose up -d --build
```

Откройте:

- http://127.0.0.1:8000/ui/ — веб-интерфейс;
- http://127.0.0.1:8000/docs — Swagger;
- http://127.0.0.1:8000/health — проверка живости.

Демо-учётки:

| Логин | Пароль | Роль |
|---|---|---|
| `viewer` | `viewer-demo` | просмотр |
| `admin` | `admin-demo` | администрирование |

При первом старте контейнер сам собирает БД из CSV в `./data` и загружает
банковские документы и новости. Если CSV нет, собирается демо-БД. База
хранится в named volume `alfa_data` и переживает перезапуск.

```bash
docker compose logs -f
docker compose down
```

Пересобрать БД после изменения CSV или паролей:

```bash
REBUILD_DB=true docker compose up -d --force-recreate
```

Удалить контейнер вместе с БД:

```bash
docker compose down -v
```

Порт меняется через `APP_PORT`, пароли — через `VIEWER_PASSWORD` и
`ADMIN_PASSWORD`.

## Локальный запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt -r requirements-core.txt
cp .env.example .env
uvicorn app.main:app --reload
```

По умолчанию `USE_DB=false`, приложение использует демо-фикстуры. Для режима
SQLite положите выгрузки в `data/`, укажите `USE_DB=true` в `.env` и соберите БД:

```bash
python -m app.db.build --db data/app.db \
  --clients data/df_Uid_data_hack.csv \
  --payments data/df_Uid_payment_hack.csv \
  --counterparties data/df_Fid_Uid_link_hack.csv --rebuild
python -m scripts.ingest_docs tests/data/bank --db data/app.db
python -m scripts.ingest_news tests/data/news --db data/app.db
```

## Данные

Ожидаемые файлы описаны в [`data/README.md`](data/README.md). Исходные CSV
большие и в git не коммитятся. Для демо-режима достаточно данных из
`tests/data/`.

## Конфигурация

Настройки читаются из окружения и `.env`; шаблон — [`.env.example`](.env.example).

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `APP_ENV` | `local` | `local`, `dev`, `staging`, `production` |
| `LOG_LEVEL` | `INFO` | уровень логирования |
| `USE_DB` | `false` | включить SQLite вместо фикстур |
| `DB_PATH` | `data/app.db` | путь к SQLite |
| `LLM_PROVIDER` | `fake` | `fake` или `remote` |
| `LLM_API_KEY` | — | ключ для remote-провайдера |
| `VIEWER_PASSWORD` | `viewer-demo` | пароль viewer при сборке БД |
| `ADMIN_PASSWORD` | `admin-demo` | пароль admin при сборке БД |
| `CORS_ORIGINS` | localhost-порты | разрешённые origin через запятую |

Пароли и `app/ml/config/llm.yaml` не коммитятся. Для remote-провайдера
используйте [`app/ml/config/llm.example.yaml`](app/ml/config/llm.example.yaml)
как шаблон.

## Тесты

```bash
pytest -q
```

## Структура

```text
app/
  main.py          сборка FastAPI, middleware, статика
  config.py        конфигурация и валидация окружения
  store.py         единый фасад над фикстурами и SQLite
  runs.py          запуски, трасса, выбор LLM
  db/              схема, загрузка CSV, репозитории, поиск
  ml/              ingest, ранжирование, retrieval, агент
  routers/         HTTP API
  schemas/         Pydantic-контракт
frontend/          SPA без сборки
scripts/           ingest документов и новостей
tests/             pytest и демо-данные
data/              локальные выгрузки (не коммитятся)
```

## Документация

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — устройство приложения и поток запроса.
- [`DB_API_MAPPING.md`](DB_API_MAPPING.md) — соответствие БД и API.
- [`data/README.md`](data/README.md) — описание выгрузок.
