# Данные

Сюда кладутся исходные выгрузки. Содержимое папки, кроме этого файла, в git
не попадает: CSV большие и не должны коммититься.

| Файл | Что внутри | Строк |
|---|---|---|
| `df_Uid_data_hack.csv` | клиенты, разделитель `;` | 85 525 |
| `df_Uid_payment_hack.csv` | платежи: `BENEFICIARY`, `PAYER`, `PAY_AMT`, `PAY_CNT` | 1 380 585 |
| `df_Fid_Uid_link_hack.csv` | привязка офисов (`SYNTHETIC_F`) к клиентам | — |

Файлы только читаются. В Docker они монтируются в контейнер, и БД собирается
автоматически при первом старте.

Локальная сборка БД:

```bash
python -m app.db.build --db data/app.db \
  --clients data/df_Uid_data_hack.csv \
  --payments data/df_Uid_payment_hack.csv \
  --counterparties data/df_Fid_Uid_link_hack.csv --rebuild
python -m scripts.ingest_docs tests/data/bank --db data/app.db
python -m scripts.ingest_news tests/data/news --db data/app.db
```

Из `df_Uid_data_hack.csv` и `df_Uid_payment_hack.csv` также можно собрать
фикстуру клиентов:

```bash
python -m scripts.build_clients_fixture
```
