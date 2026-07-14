# Фронтенд (React + Vite)

Монорепо (npm workspaces): общий модуль каталога переиспользуется мини-приложением и лендингом.

```
frontend/
├── packages/ui/       общий слой: дизайн-токены, <CatalogView>, карточка, монограмма, api, типы
├── apps/miniapp/      Telegram/MAX WebApp — готово (Спринт 2)
├── apps/landing/      лендинг (тот же CatalogView, кнопка → deep link в бот) — далее
└── apps/admin/        AdminUI — далее (Спринты 5, 8)
```

## Мини-приложение (готово)
Дизайн «бутик-ателье»: галерейный фон, кобальтовый акцент, шрифты Unbounded + Onest + JetBrains Mono,
подпись бренда — монограмма-гравировка на карточках. Разделы по ТЗ: Каталог · О нас · Отзывы · Избранное.
Данные — из живого API (`GET /api/v1/catalog`). «Выбрать для заказа»: в Telegram — `WebApp.sendData`
+ нативная MainButton, вне Telegram (лендинг) — deep link в бот. Избранное пока в localStorage
(серверная привязка — при появлении эндпоинтов).

### Запуск
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (мини-приложение)
npm run build      # production-сборка
npm run lint       # typecheck (tsc)
```
В dev запросы `/api` проксируются на живой backend `https://test.skypath.fun`
(переопределяется `VITE_PROXY_TARGET`). Для прода задать `VITE_API_BASE` и включить CORS на backend.

## Дальше
- Лендинг: переиспользовать `<CatalogView>` из `packages/ui`, кнопка ведёт в бот (deep link).
- Избранное и отзывы — подключить к серверным эндпоинтам (когда появятся в бэкенде).
- AdminUI — Спринты 5 и 8.
