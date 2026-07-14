# Контракты API (черновик под ревью)

Базовый префикс: `/api/v1`. Живой OpenAPI: `GET /docs` (Swagger), `GET /openapi.json`.
В Спринте 0 реализован каталог; остальные — по спринтам. Ниже — целевой контракт для согласования до кодирования (deliverable Спринта 0).

## Публичные (мини-приложение + лендинг)
| Метод | Путь | Назначение | Спринт |
|---|---|---|---|
| GET | `/catalog` | Список типов чехлов (без cost/margin) | 0 ✅ |
| GET | `/catalog/{id}` | Карточка типа + доступность по моделям | 2 |
| GET | `/reviews` | Опубликованные отзывы | 2 |
| GET | `/favorites?client=…` | Избранное клиента | 2 |
| POST | `/favorites` | Добавить/удалить из избранного | 2 |

## Бот (внутренний, аутентификация по сервис-токену)
| Метод | Путь | Назначение | Спринт |
|---|---|---|---|
| POST | `/orders` | Создать заказ по web_app_data | 3 |
| PATCH | `/orders/{id}` | Обновить (модель, материалы, адрес, доставка) | 3–6 |
| POST | `/orders/{id}/payment-link` | Выставить ссылку (kind=pre/post/delivery) | 4 |
| GET | `/clients/by-channel/{channel}/{uid}` | Найти/распознать клиента | 3 |
| POST | `/clients` | Регистрация клиента (контакт) | 3 |
| POST | `/promo/activate` | Активировать промокод | 3 |

## Webhooks (внешние системы)
| Метод | Путь | От кого | Спринт |
|---|---|---|---|
| POST | `/webhooks/payment/{gateway}` | Платёжный шлюз (идемпотентно) | 4 |
| POST | `/webhooks/delivery/{service}` | Служба доставки (статусы, трек) | 6 |

## AdminUI (JWT, роли admin/designer)
| Метод | Путь | Роль | Спринт |
|---|---|---|---|
| POST | `/admin/auth/login` | — | 1 |
| GET/POST/PATCH | `/admin/case-types` | admin | 2 |
| GET | `/admin/orders` (фильтры/поиск) | оба | 5 |
| GET/PATCH | `/admin/orders/{id}` | оба (поля по роли) | 5 |
| POST | `/admin/orders/{id}/mockup` | designer (триггерит отправку) | 5 |
| GET | `/admin/orders/export.xlsx` | admin | 5 |
| GET/PATCH | `/admin/clients/{id}` (скидки) | admin | 5 |
| GET/PATCH | `/admin/reviews` (модерация) | admin | 6 |
| GET/PATCH | `/admin/bot-messages` | admin | 8 |
| POST | `/admin/broadcasts` | admin | 8 |
| GET/POST | `/admin/users` | admin | 8 |

## Соглашения
- Финансовые поля не сериализуются для роли Дизайнер (отдельные схемы ответа).
- Все webhook'и идемпотентны по `idempotency_key`; повтор — 200 без побочных эффектов.
- Ссылки оплаты зависят от канала: TG → юр.лицо СНГ, MAX → юр.лицо РФ.
