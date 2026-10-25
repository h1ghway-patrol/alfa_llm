
Запуск:

docker build -t alfa-llm .
docker run --rm --env-file .env -p 5173:80 alfa-llm

Сайт:
http://localhost:5173

API внутри контейнера:
http://127.0.0.1:8000

Публичный API через nginx:
http://localhost:5173/api/

Swagger:
http://localhost:5173/api/docs

Health:
http://localhost:5173/api/health
