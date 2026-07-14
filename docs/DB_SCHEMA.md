# Модель данных (базовый этап)

Источник: ТЗ v2.0. Реализация — `backend/app/models/`. СУБД: PostgreSQL 16.

## Таблицы

### clients — БД Клиентов
Один человек в ТГ и МАКС = два разных клиента (не объединяются). Скидки — вручную.
- `id`, `phone`, `channel` (tg/max), `channel_user_id` (tg_id/max_id), `nickname`, `date_start`
- Мастер-код: `master_code`, `date_master_code`, `discount_master_code`
- Slave-код: `slave_code` (авто-генерация, уникален), `discount_slave_code`, `number_slave`, `discount_for_slave`
- Лояльность/итог: `number_orders`, `loyal_discount`, `total_discount`
- Уникальность: `(channel, channel_user_id)`
- `total_discount = loyal_discount + discount_for_slave + discount_master_code` (пересчёт при изменении компонента)

### case_types — БД Чехлов
- `id`, `name`, `is_custom`, `description`, `photo_url`, `is_active`
- Финансы (скрыто от Дизайнера): `cost` (Себес), `margin` (Маржа)
- `client_price = cost + margin` — расчётное, единое для типа (не зависит от модели)

### case_type_models — доступность по моделям iPhone
- `case_type_id`, `model_name` («iPhone 15 Pro»…), `is_available`; уникальность `(case_type_id, model_name)`
- Хранение моделей строкой в отдельной таблице (а не колонками) — расширяемо под новые модели без миграции схемы

### orders — БД Заказов
- Связи: `client_id`, `case_type_id`; `branch` (standard/custom), `model_name`, `status`
- Материалы: `materials_text`, `materials_files` (JSON: ссылки Я.Диск /client/), `custom_text` (имя/буква), `mockup_url` (/design/)
- Финансы (скрыто от Дизайнера): `cost`, `margin`, `total_discount`, `delivery_cost`, `final_price`
- Доставка: `delivery_service`, `delivery_address`, `tracking_code`, `payment_status`
- `payment_link_issued_at` — точка отсчёта напоминаний и авто-отмены (72 ч)
- `ai_analysis` (JSON) — **задел под этап 3**, в этапе 1 не используется

### order_status_history — история статусов
- `order_id`, `status`, `changed_by` (system/admin_user.id), `trigger`, `created_at`

### favorites — избранное
- `client_id`, `case_type_id`, `created_at`; уникальность `(client_id, case_type_id)`. Не синхронизируется между каналами.

### reviews — отзывы (с модерацией)
- `client_id`, `order_id`, `text`, `photo_url`, `author_name`, `status` (pending/published/rejected)

### promo_activations — активации промокодов
- `client_id` (один мастер-код на клиента), `code`, `owner_client_id`, `discount`, `created_at`

### bot_messages — тексты сообщений бота
- `code` (msg_001…), `trigger`, `text`, `buttons` (JSON), `mode` (auto/manual), `channel_tg`, `channel_max`
- `scenario_type` (base/triggered) — **задел под этап 2** (триггерные сценарии)

### broadcasts — ручные рассылки
- `text`, `segment` (JSON-фильтры), `created_by`, `sent_at`, `recipients_count`

### admin_users — пользователи AdminUI
- `email`, `full_name`, `password_hash`, `role` (admin/designer), `is_active`

### payments — транзакции оплаты
- `order_id`, `kind` (prepayment/postpayment/delivery), `gateway`, `amount`, `status`
- `external_id`, `payment_url`, `idempotency_key` (уникален — защита от двойной обработки webhook), `raw_webhook`, `paid_at`

## Заделы под будущие этапы (по требованию ТЗ)
- `orders.ai_analysis` — ИИ-анализ заказа (этап 3)
- `bot_messages.scenario_type` — триггерные сценарии (этап 2)

## RBAC
Поля Себес/Маржа/скидка/стоимость доставки/итог скрываются от роли Дизайнер **на уровне сериализации API**, не только в UI.
