# Деплой на выделенный VPS 185.207.65.130

VPS: Ubuntu 26.04, 3 CPU / 4 ГБ RAM / 77 ГБ SSD. Hostname `msk-1-vm-casetop`.
IPv4 `185.207.65.130`. Сервер выделенный — Caddy слушает 80/443 напрямую.

## Что развёрнуто
- Проект на сервере: `/opt/casetop/`
- Compose-проект `casetop`: `backend`, `postgres`, `redis`, `bot`, `bot_max`, `caddy`
- Postgres/Redis — только внутри сети проекта
- Backend внутри сети на `:8000`; на хосте только `127.0.0.1:8090` (отладка)
- Caddy публикует **80/443** → `backend:8000`
- Секреты — в `/opt/casetop/infra/.env.server` (права 600, не в git)
- Публичный домен: **https://кейстоп.рф** (`xn--e1aibsfkh.xn--p1ai`)

## Команды эксплуатации (на сервере)
```bash
cd /opt/casetop/infra
COMPOSE="docker compose -p casetop --env-file .env.server -f docker-compose.server.yml --profile bots --profile max"

$COMPOSE ps                      # статус
$COMPOSE logs -f backend         # логи
$COMPOSE up -d --build           # пересобрать/обновить
$COMPOSE down                    # остановить (данные в volume сохраняются)
```

## Обновление кода (с локальной машины)
```bash
cd ~/Documents/ЧехлыИИ
rsync -az --delete --exclude '.git' --exclude 'backend/.venv' --exclude '**/__pycache__' \
  --exclude 'infra/.env.server' --exclude 'backend/.env' --exclude 'bots/.env' \
  --exclude 'node_modules' --exclude 'frontend/node_modules' --exclude 'bots/xray' \
  -e "ssh -p 22" ./ root@185.207.65.130:/opt/casetop/
# затем на сервере: $COMPOSE up -d --build
```

## Домен и HTTPS
NS домена — **Reg.ru** (`ns1.reg.ru`, `ns2.reg.ru`). Нужные записи:

| Тип | Имя | Значение |
|---|---|---|
| A | `@` (кейстоп.рф) | `185.207.65.130` |
| A | `www` | `185.207.65.130` |

**AAAA для `@` и `www` лучше удалить.** IPv6 у Timeweb с части сетей (мобильный Happy Eyeballs) зависает, браузер не откатывается на IPv4 — сайт «не открывается» без VPN. IPv4 из Москвы проверяется (HTTP 200).

После смены A-записи Caddy сам выпускает Let's Encrypt. `www` и apex оба отдают сайт. В BotFather для Mini App указать `https://кейстоп.рф`.

## Безопасность
- Вход по SSH-ключу (`root@185.207.65.130`).
- UFW: 22, 80, 443, 10050 (агент мониторинга хостинга).
