# Спринт 0 — отчёт о выполнении

Дата: 2026-07-14. Стадия: фундамент проекта и снятие рисков.

## Что сделано (инженерная часть)

**Репозиторий и инфраструктура**
- Структура монорепо: `backend/`, `bots/`, `frontend/`, `infra/`, `docs/`
- `infra/docker-compose.yml` — PostgreSQL 16 + Redis 7 + backend (авто-миграции при старте)
- `infra/README-vkcloud.md` — карта адаптации под VK Cloud (Object Storage, Container Registry, managed БД)
- `infra/.env.example` — все переменные окружения
- `.github/workflows/ci.yml` — CI: ruff (lint+format) + pytest для backend, lint+build для frontend
- `.gitignore`

**Backend (FastAPI, Python 3.12)**
- Скелет приложения: `/health`, Sentry, роутер `/api/v1`
- Конфигурация (pydantic-settings), async-доступ к БД (SQLAlchemy 2.0)
- Перечисления домена: каналы, ветки, роли, **21 статус заказа**, платежи, доставка, модерация
- ORM-модели всех 12 таблиц (clients, case_types, case_type_models, orders, order_status_history, favorites, reviews, promo_activations, bot_messages, broadcasts, admin_users, payments)
- **Заделы под будущие этапы:** `orders.ai_analysis` (этап 3), `bot_messages.scenario_type` (этап 2)
- Сервисы: машина статусов заказа (переходы + валидация), движок цены и скидок (формулы ТЗ)
- Каталог API (чтение) — общий источник для мини-приложения и лендинга; финансовые поля не отдаются публично
- Alembic сконфигурирован (авто-генерация первой миграции — при поднятом postgres)

**Проверки (все зелёные)**
- `ruff check` + `ruff format --check` — без замечаний
- `pytest` — 12 тестов (FSM заказа + формулы цены/скидок) проходят
- Импорт всего приложения и маппинг 12 таблиц — без ошибок

**Документы-спецификации (deliverable спринта)**
- `DB_SCHEMA.md`, `ORDER_FSM.md`, `API_CONTRACT.md` — на ревью заказчику до кодирования спринта 1
- `MAX_SPIKE.md`, `DELIVERY_VERIFICATION.md`, `ACCESS_CHECKLIST.md` — планы снятия рисков

## Что требует действий заказчика/DevOps (внешнее)
Эти пункты Спринта 0 не выполнимы кодом — вынесены в чек-листы:
1. **Spike MAX (R1/R2):** нужен токен тестового MAX-бота → выполнить по `MAX_SPIKE.md`
2. **Доставка (R4):** изучить доки СДЭК, запросить доки Яндекс/Озон, согласовать флоу → `DELIVERY_VERIFICATION.md`
3. **Доступы:** VK Cloud, Яндекс Диск, боты, Sentry, UptimeRobot → `ACCESS_CHECKLIST.md`
4. **Выбор платёжных шлюзов (R3):** подтвердить до Спринта 4

## Локальный запуск — настроен и проверен
Так как Docker на машине не установлен, выбран **нативный запуск** на Homebrew-сервисах
(PostgreSQL 17 + Redis). Docker Compose сохранён для VK Cloud. Проверено сквозным прогоном:
- Первая миграция сгенерирована и применена — создано 12 таблиц
- Демо-данные посеяны: 1 админ, 3 типа чехлов (по 9 моделей iPhone), 25 текстов бота
- Сервер отдаёт `/health` = ok и `/api/v1/catalog` (цена 1200 = себес+маржа, финансы наружу скрыты)
- Пересборка с нуля (`make reset-db`) воспроизводима, ошибок нет

Инструмент: корневой `Makefile` (install/services/db/migrate/seed/run/test/lint/reset-db) и `docs/LOCAL_DEV.md`.

```bash
make services && make install && make db && make migrate && make seed && make run
curl http://localhost:8000/health
```

## Готовность к Спринту 1
Фундамент компилируется, протестирован и работает локально. Спринт 1 (аутентификация/RBAC,
CRUD каталога/клиентов/заказов, интеграция Яндекс Диск) идёт локально; деплой в VK Cloud —
после полной готовности сборки и получения доступов.
