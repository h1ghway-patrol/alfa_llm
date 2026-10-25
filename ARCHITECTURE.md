# Как устроен код

Документ для человека, который впервые открывает репозиторий: что где лежит,
как проходит запрос, чем отличаются режимы данных и где менять поведение.

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt -r requirements-core.txt
uvicorn app.main:app --reload
```

- `/docs` — Swagger со всеми эндпоинтами и схемами.
- `/health` — проверка живости.
- `pytest -q` — тесты.

Настройки читаются из `.env` (если файл есть) и из окружения. Один источник
правды — `.env.example`:

```bash
cp .env.example .env
```

Пароли по умолчанию — `viewer-demo` и `admin-demo`, те же значения читает
сборка БД. Переменные окружения перекрывают `.env`.

### Docker

```bash
docker compose up -d --build
docker compose logs -f
```

- `http://127.0.0.1:8000/ui/` — интерфейс, `/docs` — Swagger.
- При первом старте контейнер собирает БД из CSV в `./data` и сам загружает
  документы и новости. Если CSV нет, собирается демо-БД.
- БД хранится в named volume `alfa_data` и переживает перезапуск контейнера.
- Порт задаётся через `APP_PORT`, пароли — через `VIEWER_PASSWORD` и
  `ADMIN_PASSWORD`.
- Пересобрать БД после изменения CSV или паролей:
  `REBUILD_DB=true docker compose up -d --force-recreate`.
- Удалить контейнер вместе с БД: `docker compose down -v`.

Локальные CSV монтируются в `/seed` только для чтения и не попадают в образ.
Сборка БД выполняется один раз при создании volume.

## Структура

```
app/
  main.py             сборка приложения: конфиг, логи, CORS, middleware,
                      обработчики ошибок, роутеры, OpenAPI
  config.py           чтение и проверка настроек из окружения
  logging_config.py   JSON-логи и request_id через contextvars
  middleware.py       RequestIdMiddleware: id запроса, X-Request-ID, замер времени
  errors.py           единый формат ошибок и обработчики исключений
  dependencies.py     текущий пользователь, сессии и проверка роли
  store.py            фасад данных: фикстуры или SQLite
  runs.py             запуски, трасса, инсайты, выбор LLM
  db/                 схема SQLite, загрузка CSV, репозитории, поиск
  ml/                 ingest, ранжирование, retrieval и агент
  routers/            эндпоинты по группам
    auth.py           POST /auth/login, GET /auth/me
    clients.py        GET /clients, /clients/{id}/profile, /clients/{id}/feed
    events.py         GET /events/{id}, GET /sources/{id}
    insights.py       инсайт, запуск, статус, вопрос, оценка
    admin.py          /admin/news, /admin/usage, /runs/{id}/trace
  schemas/            контракт API на Pydantic (34 модели)
  fixtures/           демо-данные в JSON, проверяются теми же моделями
tests/                pytest: API, БД, ML-пайплайн и демо-данные
data/                 исходные CSV (в git не попадают)
```

## Путь запроса

1. `RequestIdMiddleware` берёт `X-Request-ID` из запроса или создаёт новый,
   кладёт его в `request.state` и в `contextvars`, чтобы он был в логах.
2. `CORSMiddleware` отвечает на preflight и ставит заголовки для разрешённых
   origin из `CORS_ORIGINS`.
3. Зависимость (`Depends`) достаёт пользователя из `Authorization: Bearer`.
   Для админских путей дополнительно проверяется роль.
4. Роутер валидирует вход моделями Pydantic и берёт данные через `app/store`
   (фикстуры или SQLite) либо через `app/runs` для запусков агента.
5. Если что-то пошло не так — ошибку ловит обработчик из `app/errors.py` и
   отдаёт её в общем формате. `request_id` попадает и в тело, и в заголовок.

## Конфигурация

`app/config.py` читает переменные один раз при старте. Если значение
неверное, приложение падает с текстом, в котором перечислены все проблемы
сразу. Проверяются:

| Переменная | По умолчанию | Проверка |
|---|---|---|
| `APP_NAME` | `alfa_llm` | — |
| `APP_ENV` | `local` | `local`, `dev`, `staging`, `production` |
| `LOG_LEVEL` | `INFO` | `DEBUG`…`CRITICAL` |
| `CORS_ORIGINS` | `localhost:5173,3000,8080` | http(s)-адреса через запятую |
| `CORS_ALLOW_CREDENTIALS` | `false` | true/false |
| `REQUEST_ID_HEADER` | `X-Request-ID` | — |
| `VIEWER_PASSWORD` | `viewer-demo` | — |
| `ADMIN_PASSWORD` | `admin-demo` | — |
| `DAILY_TOKEN_LIMIT_TOKENS` | не задан | целое > 0 |
| `BUDGET_RUB` | не задан | число > 0 |

Смысл: неверная настройка видна сразу при запуске, а не через час в проде.

## Авторизация (заглушка)

`app/dependencies.py` знает две учётки — `viewer` и `admin`. Пароли берутся
из окружения, токены живут в памяти процесса. Токен разбирает `HTTPBearer`,
поэтому в Swagger есть кнопка **Authorize**: вставьте токен из
`POST /auth/login`, и `/docs` начнёт отправлять его сам. `require_role("admin")`
закрывает админку.

Это временно: задача B-4 заменит её на пользователей и сессии в БД. Роутеры
трогать не придётся — они зависят только от `get_current_user` и
`require_role`.

## Ошибки и request_id

Любой ответ с ошибкой выглядит одинаково:

```json
{"error": {"code": "not_found", "message": "Клиент U_999 не найден", "request_id": "..."}}
```

- `code` — машиночитаемый, snake_case.
- `message` — по-русски, для человека.
- `request_id` — тот же, что в заголовке `X-Request-ID` и в логах.

Обработчики покрывают `HTTPException`, ошибки валидации (422) и любые
непойманные исключения (500). На 500 клиент не видит внутренностей, а в
логах остаётся трассировка.

## Режимы данных и агент

`app/fixtures/*.json` — демо-данные для режима `USE_DB=false`: клиенты,
события, готовые инсайты, источники и оценки релевантности. При импорте они
проходят через те же Pydantic-модели, что и ответы API: сломанная фикстура
роняет старт, а не отдаёт фронту мусор.

При `USE_DB=true` источником становится SQLite:

- `app/store.py` скрывает разницу между фикстурами и БД от роутеров;
- `app/db/` содержит схему, загрузчики CSV, репозитории и FTS5-поиск;
- `app/ml/pipeline.py` размечает новости и считает релевантность;
- `app/ml/agent/` строит инсайт, пишет трассу и проверяет результат.

Запуск интерпретации:

1. `POST .../insight` — если готовый инсайт есть, отдаёт `200`; иначе
   создаёт запуск и отдаёт `202` с `run_id`.
2. `GET /runs/{run_id}` — статус запуска.
3. `GET /runs/{run_id}/trace` — шаги, только для `admin`.
4. `GET .../insight` — готовый инсайт.

В режиме фикстур запуски живут в памяти и теряются при перезапуске. В режиме
БД запуски, трасса, инсайты, сессии и обратная связь сохраняются в SQLite.

## Эндпоинты

| Метод и путь | Роль | Что делает |
|---|---|---|
| `POST /auth/login`, `GET /auth/me` | — / любая | вход, текущий пользователь |
| `GET /clients` | viewer | список клиентов |
| `GET /clients/{id}/profile` | viewer | профиль и теги |
| `GET /clients/{id}/feed` | viewer | лента, фильтры `topic`, `limit` |
| `GET /events/{id}` | viewer | событие без персонализации |
| `POST /clients/{id}/events/{eid}/insight` | viewer | `202` + `run_id` или `200` + инсайт |
| `GET /runs/{run_id}` | viewer | статус запуска |
| `GET /clients/{id}/events/{eid}/insight` | viewer | готовая интерпретация |
| `POST /clients/{id}/events/{eid}/ask` | viewer | уточняющий вопрос |
| `GET /sources/{id}` | viewer | первоисточник |
| `GET /runs/{run_id}/trace` | admin | шаги агента |
| `POST /feedback` | viewer | оценка `-1`/`1` (👍/👎) |
| `POST /admin/news` | admin | добавить новость |
| `GET /admin/usage` | admin | токены по дням |
| `GET /health` | — | живость |

## Схемы

Модели лежат в `app/schemas` по темам и перечислены в `ALL_MODELS`
(`app/schemas/__init__.py`). `app/main.py` добавляет все модели в
`components/schemas` OpenAPI, поэтому `/docs` показывает полный контракт
сразу, даже если эндпоинт ещё не написан.

Договорённости:

- у сущности поле `id`, у ссылки на неё — `client_id`, `event_id`, `source_id`;
- перечисления (`kind`, `status`, `freshness`) — `Literal`, словари не нужны;
- у каждого поля есть `description`, у ключевых моделей — `examples`;
- новая модель добавляется в `ALL_MODELS` и `__all__`.

## Тесты

| Файл | Что проверяет |
|---|---|
| `tests/test_api_contract.py` | сквозной сценарий фронта на заглушках |
| `tests/test_errors.py` | формат ошибок, `X-Request-ID`, 422/401/404 |
| `tests/test_config.py` | чтение настроек и падение на неверных значениях |

## Стык с БД

Все расхождения с `schema.sql` и правила преобразования колонок в поля API —
в `DB_API_MAPPING.md`. Кратко:

- ID в API строки, в БД числа; `str(id)` делает репозиторий, а тип `Id`
  в схемах дополнительно принимает числа;
- `feedback.rating` — `-1`/`1`, как в `CHECK` и в интерфейсе;
- `published_at` и `source_name` могут быть `null`;
- `company_age_band` → `age_band`, `document.status` → `freshness`;
- пароли — только из `.env` (`viewer-demo` / `admin-demo`).

## Данные

Исходные CSV кладутся в `data/` в корне репозитория. Папка в git не
попадает (кроме `data/README.md`): файлы большие, и по заданию их нельзя
коммитить. Грузить их в БД будет DB-2/DB-3.

Фикстура клиентов собирается из реальных выгрузок:

```bash
python -m scripts.build_clients_fixture
```

Скрипт берёт демо-клиентов `U_1465`, `U_51606`, `U_57706`, выбрасывает
клиентов с дублирующимся ID, считает продукты, корзину выручки, размер
группы, контрагентов и теги. Новости и источники пока остаются заглушкой:
для них нужны md-документы банка.

## Что дальше

- B-4 — настоящая авторизация и сессии.
- B-5 — схема БД и репозитории вместо фикстур.
- B-6 — агент, `TraceRecorder`, реальный инсайт.
- B-3.5 / B-7 — загрузка CSV и подключение к ленте.

Правило, которое стоит держать в голове: наружу отдаём только схемы из
`app/schemas`, а источники данных (фикстуры, потом БД) прячем за функциями
в `app/fixtures` и `app/runs`. Тогда замена заглушки на реальную реализацию
не меняет контракт для фронта.
