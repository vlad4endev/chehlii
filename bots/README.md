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
| `REDIS_URL` | Redis для FSM Telegram (`redis://localhost:6379/1`) |

## Отличия канала MAX (по итогам spike, см. `docs/MAX_SPIKE.md`)

- **Контакт (R1):** основной путь — текстовый ввод телефона `+7XXXXXXXXXX` с валидацией;
  дополнительно предлагается нативная кнопка «Поделиться контактом» (best-effort).
- **Выбор из мини-приложения (R2):** в MAX нет аналога `WebApp.sendData`. Мини-приложение
  создаёт заказ через backend и открывает бота с deep-link `order_<id>`; бот подхватывает
  заказ по id (`GET /orders/{id}`) и показывает подтверждение.
- **Клавиатуры:** в MAX это inline-вложения сообщения (reply-клавиатур нет). Каталог —
  кнопка `OpenApp` (мини-приложение привязано к боту).
- **Публикация:** боты и мини-приложения MAX публикуются только через верифицированные
  юрлица РФ — для боевого запуска нужен верифицированный аккаунт.

## Docker

`Dockerfile` по умолчанию запускает Telegram (`bots.run`). Для MAX в compose добавляется
второй сервис с `command: python -m bots.run_max`.
