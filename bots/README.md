# Боты

Наполняется в Спринтах 3 (Telegram) и 7 (MAX).

```
bots/
├── core/   общий FSM-сценарий, тексты из БД, канал-независимая логика
├── tg/     aiogram 3, handler web_app_data
└── max/    адаптер MAX Bot API поверх core (см. docs/MAX_SPIKE.md)
```

Ядро (`core/`) канал-независимо; `tg/` и `max/` — тонкие адаптеры ввода/вывода. Оплата и статусы приходят из backend.
