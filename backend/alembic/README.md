# Миграции

Автогенерация первой миграции (после поднятия postgres):

```bash
docker compose -f ../infra/docker-compose.yml run --rm backend \
    alembic revision --autogenerate -m "initial schema"
docker compose -f ../infra/docker-compose.yml run --rm backend alembic upgrade head
```

При старте контейнера `backend` миграции применяются автоматически (`alembic upgrade head` в команде compose).
