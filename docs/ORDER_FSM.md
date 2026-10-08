# Машина статусов заказа

Источник: модель статусов ТЗ v2.0. Реализация: `backend/app/services/order_state_machine.py`.
Ветки: **а — Стандарт** (имя/буква, без макета), **б — Кастом** (материалы → макет → согласование).

## Диаграмма переходов

```
case_type_selected → model_selected → case_confirmed
   ├─ (Стандарт) → prepayment_issued
   └─ (Кастом)   → materials_submitted → prepayment_issued

prepayment_issued ─(webhook)→ prepayment_paid          ┐ авто-отмена 72ч / ручная → cancelled
prepayment_paid
   ├─ (Стандарт) → postpayment_issued
   └─ (Кастом)   → handed_to_design → design_in_progress → mockup_sent
                       mockup_sent → mockup_approval → postpayment_issued
                       mockup_sent → mockup_revision → mockup_sent (цикл)

postpayment_issued ─(webhook)→ postpayment_paid        ┘ авто-отмена 72ч / ручная → cancelled
postpayment_paid → delivery_service_selection → delivery_address_selection
   → delivery_payment ─(webhook)→ shipped ─(webhook)→ delivered
   → review_offered → review_received
```

## Кто меняет статус

| Триггер | Кто | Тип |
|---|---|---|
| WebApp.sendData, выбор модели, подтверждение, отправка материалов | Система | Авто |
| Webhook предоплаты/постоплаты | Система | Авто |
| «Передан в дизайн», «Дизайн в процессе» | Дизайнер | Вручную |
| Загрузка макета → «Отправка макета» + отправка клиенту | Система (триггер при загрузке файла) | Авто |
| Клиент «Подтвердить»/«Переделать» макет | Система | Авто |
| Выбор службы/адреса, оплата доставки, webhook доставки | Система | Авто |
| Отмена: 72 ч без оплаты **или** вручную дизайнером | Система/Дизайнер | Оба |

## Важные правила
- «Отправка макета» **не** ставится дизайнером вручную — это триггер при загрузке файла в AdminUI (Я.Диск → статус → отправка в бот).
- Терминальные статусы: `review_received`, `cancelled` — выходов нет.
- Любой недопустимый переход отклоняется (`InvalidTransition`), покрыто тестами `tests/test_order_state_machine.py`.

## Уведомления клиенту при ручной смене статуса

Реализация: `backend/app/services/order_status_notify.py`. При `PATCH /admin/orders/{id}/status` (и force) клиенту уходит сценарий из `bot_messages`:

| Статус | Сообщение |
|---|---|
| `prepayment_issued` | `msg_007а` / `msg_007б` + кнопка оплаты |
| `prepayment_paid` | `msg_008а` / `msg_008б` (как после webhook) |
| `postpayment_issued` | `msg_010б_x` + кнопка постоплаты |
| `postpayment_paid` | `msg_011аб` → выбор доставки |
| `delivery_service_selection` | `msg_011аб` + блок выбора службы |
| `shipped` | `msg_014аб` |
| `delivered` | `msg_015аб` → авто `review_offered` + `msg_016` |
| `review_offered` | `msg_016` |
| `review_received` | `msg_017` |
| `cancelled` | `msg_cancel` |

**Исключение:** `mockup_sent` / `mockup_approval` / `mockup_revision` при ручной смене **не** шлют сообщение. Согласование макета (`msg_009аб` + кнопки) — только при «Загрузить и отправить».
