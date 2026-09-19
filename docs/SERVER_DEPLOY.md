# Деплой на выделенный VPS 147.45.96.86

VPS: Ubuntu 26.04, 3 CPU / 4 ГБ RAM / 77 ГБ SSD. Hostname `msk-1-vm-casetop`, нода `kvmnvm-1034`.
IPv4 `147.45.96.86`, IPv6 `2a03:6f00:a::f026`. Сервер выделенный — Caddy слушает 80/443 напрямую.

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
  -e "ssh -p 22" ./ root@147.45.96.86:/opt/casetop/
# затем на сервере: $COMPOSE up -d --build
```

## Домен и HTTPS
NS домена — **Reg.ru** (`ns1.reg.ru`, `ns2.reg.ru`). Нужные записи:

| Тип | Имя | Значение |
|---|---|---|
| A | `@` (кейстоп.рф) | `147.45.96.86` |
| A | `www` | `147.45.96.86` |
| AAAA | `@` | `2a03:6f00:a::f026` |
| AAAA | `www` | `2a03:6f00:a::f026` |

После смены A-записи Caddy сам выпускает Let's Encrypt. `www` и apex оба отдают сайт.

Пока DNS не переключён, сайт доступен по `http://147.45.96.86/`.

Затем остановить ботов на старом сервере и поднять их здесь (`--profile bots --profile max`), иначе два поллера с одним токеном конфликтуют. В BotFather для Mini App указать `https://кейстоп.рф`.

## Безопасность
- Вход по SSH-ключу (`root@147.45.96.86`). Пароль root передавался открытым текстом — смените его в панели хостинга.
- UFW: 22, 80, 443, 10050 (агент мониторинга хостинга).
