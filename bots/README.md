# Боты

Один backend обслуживает все платформы. Ядро (`core/`) канал-независимо; `tg/` и `max/`
— тонкие адаптеры ввода/вывода. Оплата, статусы и данные приходят из backend.

```
bots/
├── core/       общий FSM-сценарий, тексты из БД, клиент backend
├── tg/         aiogram 3, приём выбора через web_app_data
├── max/        maxapi, приём выбора через backend (deep-link order_<id>)
├── run.py      точка входа Telegram   (python -m bots.run)
└── run_max.py  точка входа MAX        (python -m bots.run_max)
```

## Запуск локально

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# секреты — в bots/.env (см. ниже)
python -m bots.run       # Telegram
python -m bots.run_max   # MAX
```

## Переменные окружения (`bots/.env`)

| Переменная | Назначение |
|---|---|
| `TG_BOT_TOKEN` | токен Telegram-бота (@BotFather) |
| `MAX_BOT_TOKEN` | токен MAX-бота (@MasterBot) — нужен для `run_max` |
| `MAX_BOT_USERNAME` | username MAX-бота (для кнопки «Каталог» → мини-приложение) |
| `BACKEND_URL` | адрес единого API (по умолчанию `http://localhost:8000/api/v1`) |
| `WEBAPP_URL` | публичный HTTPS-URL мини-приложения (Telegram WebApp) |
| `REDIS_URL` | Redis для FSM Telegram и MAX (`redis://localhost:6379/1`) |

## Отличия канала MAX (по итогам spike, см. `docs/MAX_SPIKE.md`)

Сценарий тот же, что в Telegram: меню → каталог → контакт → подтверждение →
имя/материалы → предоплата → макет → остаток → доставка → консультация.

- **Контакт (R1):** кнопка «Поделиться контактом» + текст `+7XXXXXXXXXX` (в Telegram
  тоже принимается текст — паритет).
- **Выбор из мини-приложения (R2):** в MAX нет `WebApp.sendData`. Мини-приложение
  создаёт заказ через backend и открывает бота с deep-link `order_<id>`; бот
  подхватывает заказ по id и показывает подтверждение.
- **FSM:** Redis (`key_prefix=maxbot`), сценарии из админки применяются сразу при
  доставке outbox — как у Telegram.
- **Клавиатуры:** inline-вложения (reply-клавиатур нет). Каталог — `OpenApp`
  (нужен `MAX_BOT_USERNAME`).
- **Публикация:** через верифицированные юрлица РФ.

## Docker

`Dockerfile` по умолчанию запускает Telegram (`bots.run`). Для MAX в compose добавляется
второй сервис с `command: python -m bots.run_max`.
