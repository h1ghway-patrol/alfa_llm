# Соответствие «БД → API»

Преобразование строки БД в форму API делают функции из `app/db/mappers.py`. Репозиторий (`repositories.py`) отдаёт
словари с именами колонок, роутер вызывает преобразователь и передаёт результат в Pydantic-модель.

```python
rows = repo.list_clients(conn)
return [ClientSummary(**mappers.to_client_summary(r)) for r in rows]
```

## Идентификаторы

| Сущность | В БД и репозитории | В API |
|---|---|---|
| Клиент | `company.id`, строка (`U_1465`) | `client_id`, строка |
| Событие (документ-новость) | `document.id`, int | `event_id`, **строка** |
| Фрагмент источника | `chunk.id`, int | `source_id`, **строка** (и в `Claim.source_ids`) |
| Инсайт | `insight.id`, int | `insight_id`, **строка** |
| Запуск | `run.id`, int | `run_id`, **строка** |

Из API в БД идентификатор разбирает `ids.parse_id(raw)`: только цифры ASCII (до 18), иначе `InvalidId` (подкласс
`ValueError`). Роутер должен превращать `InvalidId` в 404 в формате ошибок проекта, а не в 500.

## Клиент: `to_client_summary`, `to_client_profile`

| Поле API | Поле БД | Преобразование |
|---|---|---|
| `client_id` | `id` | переименование |
| `industry` | `okved_name` | копия (то же, что `okved_name`) |
| `okved_code`, `okved_name`, `city`, `region` | одноимённые | без изменений |
| `revenue_band`, `employees_band` | одноимённые | без изменений |
| `age_band` | `age_band` | без изменений (колонка называется так же) |
| `is_demo` | `is_demo` | 0/1 → bool |
| `products` | `has_loan`, `has_leasing`, `has_guarantee`, `has_deposit`, `has_rko`, `has_payroll`, `has_factoring` | список названий продуктов, у которых флаг равен 1 |

Только в профиле:

| Поле API | Поле БД | Преобразование |
|---|---|---|
| `revenue_rub`, `ownership`, `business_stage`, `client_type`, `group_id`, `group_size` | одноимённые | без изменений, могут быть `null` |
| `is_large` | `is_large` | 0/1 → bool |
| `has_loan` … `has_fts` (8 флагов) | одноимённые | 0/1 → bool, NULL → `null` («неизвестно», не «нет») |
| `unknown_features` | флаги `has_*` | имена флагов, у которых NULL |
| `fts_countries` | `fts_countries` | строка через запятую → список строк, пусто → `[]` |
| `key_owner_mark` | `key_owner_mark` | 0/1 → bool, NULL → `null` |
| `tags` | вычисляется в ML (`build_profile`) | передаётся вторым аргументом: список `{name, label, evidence}` |

## Лента, событие, источник: `to_feed_item`, `to_event`, `to_source_fragment`

| Поле API | Источник | Преобразование |
|---|---|---|
| `FeedItem.event_id` | `document.id` | int → строка |
| `FeedItem.published_at` | `document.doc_date` | без изменений, может быть `null` |
| `FeedItem.topics` | `doc_topic.topic` | список |
| `FeedItem.relevance_score` | `relevance.score` | 0–1 |
| `FeedItem.relevance_reasons` | `relevance.reasons_json` | JSON → список, не больше 3 |
| `FeedItem.has_insight` | `insight` существует и `status='done'` | bool |
| `event.published_at`, `event.freshness` | `doc_date`, `status` | переименование |
| `event.facts` | `facts_json` | JSON → объект, `null` до разметки |
| `SourceFragment.source_id` | `chunk.id` | int → строка |
| `SourceFragment.freshness` | `document.status` | `actual` / `outdated` / `unknown` |

## Запуск и инсайт: `to_run`, `to_insight`, `to_trace_step`

| Поле API | Источник | Преобразование |
|---|---|---|
| `Run.run_id`, `Run.insight_id` | `run.id`, `insight.id` | int → строка, `insight_id` может быть `null` |
| `Insight.insight_id`, `event_id` | `insight.id`, `insight.doc_id` | int → строка |
| `Insight.<блоки>` | `insight.body_json` | JSON → списки `Claim` |
| `Claim.source_ids` | `body_json` | список int → список строк |
| `Claim.client_features` | `body_json` | только для `kind='client'` (поле добавлено сверх контракта) |
| `Insight.data_quality_notes` | `body_json` | список строк |
| `TraceStep.input`, `output` | `input_json`, `output_json` | JSON → объект |

## Что изменилось по сравнению с прошлой версией

- Строка `company_age_band → age_band` убрана: в БД колонка уже называется `age_band`.
- Добавлены `client_id`, `products`, булевы флаги, `unknown_features`, `fts_countries`.
- Идентификаторы документов, фрагментов, инсайтов и запусков в API — строки.
