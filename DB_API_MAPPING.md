# Соответствие БД ↔ API

Единая таблица соответствий, чтобы склейка слоёв не расходилась. Правило
простое: наружу отдаются только модели из `app/schemas`, а преобразование
колонок БД в поля API живёт на границе репозитория (`app/db/repositories.py`).

## Решения по расхождениям

| Вопрос | Решение | Почему |
|---|---|---|
| Формат ID | В API всегда **строка**. В БД `INTEGER`. Преобразование `str(id)` на границе репозитория. Схемы принимают и числа: тип `Id` в `app/schemas/common.py` приводит `int` → `str`. | Фронт уже работает со строками, ID для него непрозрачны. Не нужно менять контракт и URL-ы. |
| `feedback.rating` | `-1` или `1`. Ограничение `CHECK (rating IN (-1, 1))` в БД остаётся. | В интерфейсе 👍/👎, а не звёзды. Меньше кода на обеих сторонах. |
| `published_at`, `source_name` | В API `datetime \| None` и `str \| None`. `NULL` из БД допустим. | Не блокируемся на данных: у документа может не быть даты (обзор без даты). Фронт показывает «дата неизвестна». |
| Имена полей | Таблица ниже. Главное расхождение: `company_age_band` → `age_band`, флаги продуктов → `products`. | Одно имя на стыке. |
| Пароли | Один источник правды — `.env.example` (`viewer-demo` / `admin-demo`). И API, и сборка БД читают `.env`. | Не два набора паролей. |

## `company` → `ClientProfile` / `ClientSummary`

| Колонка БД | Поле API | Преобразование |
|---|---|---|
| `id` | `client_id` | `str(id)` |
| `okved_code` | `okved_code` | как есть |
| `okved_name` | `okved_name` | как есть |
| `city` | `city` | как есть |
| `region` | `region` | как есть |
| `revenue_rub` | `revenue_rub` | как есть (только в профиле) |
| `revenue_band` | `revenue_band` | как есть |
| `employees_band` | `employees_band` | как есть |
| `company_age_band` | `age_band` | **переименование** |
| `ownership` | `ownership` | как есть |
| `client_type` | `client_type` | как есть |
| `has_loan`, `has_leasing`, `has_guarantee`, `has_deposit`, `has_rko`, `has_payroll`, `has_factoring` | `products` | собрать список кодов с флагом `1` |
| `has_fts`, `fts_countries` | `fts_countries` | страны строкой через запятую → список; пусто → `[]` |
| `group_id` | `group_id` | как есть |
| `group_size` | `group_size` | как есть |
| `is_large` | `is_large` | `0/1` → `bool` |
| `is_demo` | `is_demo` | `0/1` → `bool` |
| `payment` (агрегат) | `payments.incoming_partners`, `payments.outgoing_partners` | считать по `payer`/`beneficiary` |
| — (ML-1) | `tags` | бизнес-теги строит ML-1, в БД не хранятся |
| `key_owner_mark`, `business_stage` | — | в API не отдаются, смысл не подтверждён |

Замечание: `revenue_rub` и `revenue_band` есть только в `ClientProfile`,
в `ClientSummary` — только `revenue_band`.

## `document` → `Event` / `FeedItem` / `SourceFragment`

| Колонка БД | Поле API | Преобразование |
|---|---|---|
| `id` | `event_id` | `str(id)` |
| `kind` | — | фильтр: событие = документ с `kind='news'` |
| `title` | `title` | как есть |
| `doc_date` | `published_at` | `date` → `datetime` (00:00 UTC), `NULL` → `None` |
| `source_name` | `source_name` | `NULL` → `None` |
| `url` | `url` | как есть |
| `status` (`actual`/`outdated`/`unknown`) | `freshness` | **переименование**: у документа `status` — это актуальность |
| `facts_json` | `facts` | JSON → `list[EventFact]` |
| `doc_topic.topic` | `topics` | список тем |
| `content_hash` | — | служебное, наружу не отдаётся |

## `chunk` → `SourceFragment`

| Колонка БД | Поле API | Преобразование |
|---|---|---|
| `id` | `source_id` | `str(id)` |
| `document.title` | `doc_title` | join по `doc_id` |
| `document.kind` | `doc_kind` | как есть |
| `document.doc_date` | `doc_date` | как есть (`date \| None`) |
| `section_path` | `section_path` | как есть |
| `text` | `text` | как есть |
| `document.url` | `url` | как есть |
| `document.status` | `freshness` | как есть |
| `position`, `lemmas` | — | служебное |

## `run`, `insight`, `insight_source`

| Колонка БД | Поле API | Преобразование |
|---|---|---|
| `run.id` | `run_id` | `str(id)` |
| `run.status` | `status` | как есть |
| `run.error` | `error` | как есть |
| `insight.id` | `insight_id` | `str(id)` |
| `insight.client_id` | `client_id` | `str(id)` |
| `insight.doc_id` | `event_id` | `str(id)` |
| `insight.status` | `status` | как есть |
| `insight.body_json` | `what_happened`, `why_it_matters`, `consequences`, `actions`, `bank_view`, `basis`, `data_quality_notes` | JSON → блоки `Insight` |
| `insight_source` | внутри `Claim.source_ids` | `str(chunk_id)` / `str(doc_id)`; `client_feature` → `basis` |
| `insight.created_at` | `created_at` | как есть |

`Insight.status` и `document.status` — разные вещи с одинаковым именем колонки.
У инсайта это `queued/running/done/failed`, у документа — актуальность
(`actual/outdated/unknown`, в API поле `freshness`).

## `trace_step` → `TraceStep`

| Колонка БД | Поле API |
|---|---|
| `step_no` | `step_no` |
| `step_type` | `step_type` |
| `tool_name` | `tool_name` |
| `input_json` | `input` |
| `output_json` | `output` |
| `model` | `model` |
| `tokens_in`, `tokens_out`, `latency_ms`, `created_at` | одноимённо |

`GET /admin/usage` агрегирует `trace_step` по дням: `usage_by_day` из
`app/db/trace.py` → `list[UsageDay]`. Сейчас, пока БД нет, та же агрегация
считается по шагам в памяти (`app/runs.py:usage_by_day`). Форма ответа не
изменится.

## `feedback`, `app_user`, `session`

| Колонка БД | Поле API |
|---|---|
| `feedback.insight_id` | `insight_id` (`str`) |
| `feedback.rating` | `rating` (`-1`/`1`) |
| `feedback.comment` | `comment` |
| `app_user.id`, `username`, `role` | `UserOut` |
| `session.token`, `expires_at` | `LoginResponse.access_token`, `expires_at` |

Пароли в API не отдаются никогда: только `access_token`.
