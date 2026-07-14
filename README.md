# ЧехлИИ

Цифровой сервис заказа индивидуальных чехлов на смартфон: боты Telegram и MAX с мини-приложениями, лендинг, CRM/AdminUI. Реализуется **Базовый этап** ТЗ v2.0; архитектура заложена расширяемой под этапы 2–3.

Документы проекта:
- [ПЛАН_РАЗРАБОТКИ.md](ПЛАН_РАЗРАБОТКИ.md) — поэтапный план (спринты 0–9)
- [docs/DB_SCHEMA.md](docs/DB_SCHEMA.md) — модель данных
- [docs/ORDER_FSM.md](docs/ORDER_FSM.md) — машина статусов заказа
- [docs/API_CONTRACT.md](docs/API_CONTRACT.md) — контракты REST API и webhook'ов
- [docs/MAX_SPIKE.md](docs/MAX_SPIKE.md) — план верификации MAX Bot API (R1, R2)
- [docs/DELIVERY_VERIFICATION.md](docs/DELIVERY_VERIFICATION.md) — проверка флоу доставки (R4)
- [docs/ACCESS_CHECKLIST.md](docs/ACCESS_CHECKLIST.md) — доступы и секреты
- [docs/SPRINT_0_REPORT.md](docs/SPRINT_0_REPORT.md) — итоги спринта 0

## Стек

PostgreSQL 16 · Redis 7 · FastAPI (Python 3.12) · aiogram 3 · React + Vite · APScheduler · Docker Compose · VK Cloud · GitHub Actions · Sentry + UptimeRobot.

## Структура репозитория

```
├── backend/          FastAPI: REST API, webhooks, бизнес-логика, scheduler
│   ├── app/
│   │   ├── core/     конфигурация, БД, безопасность
│   │   ├── models/   ORM-модели (SQLAlchemy 2.0)
│   │   ├── services/ FSM заказа, движок скидок
│   │   ├── api/      роутеры v1
│   │   ├── payments/ адаптеры платёжных шлюзов (Strategy) — Спринт 4
│   │   ├── delivery/ адаптеры служб доставки (Strategy)   — Спринт 6
│   │   └── storage/  клиент Яндекс Диск                    — Спринт 1
│   └── alembic/      миграции
├── bots/             tg / max поверх общего FSM-ядра         — Спринты 3, 7
├── frontend/         miniapp / landing / admin (React)       — Спринты 2, 5, 8
├── infra/            docker-compose, конфигурация VK Cloud
└── docs/             спецификации и отчёты
```

## Быстрый старт (локально)

```bash
cd infra
cp .env.example .env          # заполнить секреты
docker compose up -d --build  # postgres + redis + backend
curl http://localhost:8000/health
open http://localhost:8000/docs
```

## Стадия

Спринт 0 (фундамент) — выполнен. Каталог `bots/` и `frontend/` наполняются в последующих спринтах.
