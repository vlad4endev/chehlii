# Локальная разработка (нативный запуск, без Docker)

Так как Docker на машине не установлен, backend запускается нативно на Homebrew-сервисах
PostgreSQL 17 и Redis. Конфигурация Docker Compose (`infra/`) сохраняется для деплоя в VK Cloud.

## Требования
- Python 3.12 (`/opt/homebrew/bin/python3.12`)
- PostgreSQL 17 и Redis (Homebrew)

## Первый запуск

```bash
make services   # brew services start postgresql@17 redis
make install    # venv + зависимости backend
make db         # роль и база chehlii
make migrate    # применить миграции (создаёт 12 таблиц)
make seed       # демо-данные: админ, каталог, тексты бота
make run        # http://localhost:8000
```

Проверка:
```bash
curl http://localhost:8000/health           # {"status":"ok","env":"local"}
curl http://localhost:8000/api/v1/catalog    # список типов чехлов
open http://localhost:8000/docs              # Swagger UI
```

## Учётные данные (локально)
- БД: `chehlii` / `chehlii` @ `localhost:5432`, база `chehlii`
- Админ AdminUI: `admin@chehlii.local` / `admin123` (используется с появлением auth в Спринте 1)

Секреты локального `backend/.env` не коммитятся. Пример — `infra/.env.example`.

## Полезное
```bash
make test       # pytest
make lint       # ruff check + format --check
make reset-db   # пересоздать базу с нуля (удаляет данные) + migrate + seed
```

## Переход на VK Cloud
Когда сборка готова: те же образы через `infra/docker-compose.yml`, провайдеры хранилища/реестра
меняются на VK (см. `infra/README-vkcloud.md`). Код приложения не меняется — только переменные окружения.
