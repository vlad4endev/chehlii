# Деплой на сервер 77.93.125.36 (staging)

VPS: Ubuntu 24.04, 4 CPU / 15 ГБ RAM. Сервер общий — на нём уже работает ~13 Docker-проектов
(supabase, n8n, nocobase, timelog, nginx_proxy_manager и др.). casetop развёрнут **изолированно**,
как отдельный compose-проект `casetop`, без вмешательства в чужие сервисы.

## Что развёрнуто
- Проект на сервере: `/home/skyputh/casetop/`
- Compose-проект `casetop`: контейнеры `casetop-backend-1`, `casetop-postgres-1`, `casetop-redis-1`
- Postgres/Redis — только внутри сети проекта (наружу не публикуются)
- Backend — host-порт **8090** → `http://77.93.125.36:8090` (для проксирования доменом через NPM)
- Секреты — в `/home/skyputh/casetop/infra/.env.server` (сгенерированы на сервере, права 600, не в git)

## Команды эксплуатации (на сервере)
```bash
cd /home/skyputh/casetop/infra
COMPOSE="docker compose -p casetop --env-file .env.server -f docker-compose.server.yml"

$COMPOSE ps                      # статус
$COMPOSE logs -f backend         # логи
$COMPOSE up -d --build           # пересобрать/обновить
$COMPOSE down                    # остановить (данные в volume сохраняются)
docker exec casetop-backend-1 python -m app.seed   # посев демо-данных
```

## Обновление кода (с локальной машины)
```bash
cd ~/Documents/ЧехлыИИ
rsync -az --delete --exclude '.git' --exclude 'backend/.venv' --exclude '**/__pycache__' \
  --exclude 'infra/.env.server' --exclude 'backend/.env' \
  -e "ssh -p 22" ./ skyputh@77.93.125.36:/home/skyputh/casetop/
# затем на сервере: $COMPOSE up -d --build
```

## Домен и HTTPS — настроено ✅
Домен **https://test.skypath.fun** проксирует на backend (172.17.0.1:8090) с доверенным
сертификатом Let's Encrypt (выпущен через certbot внутри контейнера `nginx_proxy_manager`,
действует до 2026-10-11), http→https редирект включён.

**Важно:** этот proxy host сделан **файлом-конфигом вручную**, а не через UI NPM, поэтому в
веб-панели NPM он не отображается. Конфиг:
`nginx_proxy_manager:/data/nginx/proxy_host/test.skypath.fun.conf`
(на хосте: `/data/compose/4/data/nginx/proxy_host/test.skypath.fun.conf`).

Обновление/правка конфига:
```bash
docker cp <новый>.conf nginx_proxy_manager:/data/nginx/proxy_host/test.skypath.fun.conf
docker exec nginx_proxy_manager nginx -t          # ОБЯЗАТЕЛЬНО перед reload
docker exec nginx_proxy_manager nginx -s reload
```

Автопродление сертификата: `certbot renew` (webroot `/data/letsencrypt-acme-challenge`); ACME-путь
`/.well-known/acme-challenge/` отдаётся без редиректа, поэтому продление не ломается.
Ручная проверка продления: `docker exec nginx_proxy_manager /opt/certbot/bin/certbot renew --dry-run`.

Если позже захотите вести домен через UI NPM: удалить файл-конфиг, затем добавить Proxy Host в
панели (`http://77.93.125.36:81`): Forward `172.17.0.1` порт `8090`, SSL → Let's Encrypt + Force SSL.

## Безопасность (важно)
- **Сменить SSH-пароль пользователя `skyputh`** — он был передан открытым текстом. Рекомендуется вход по SSH-ключу.
- После настройки домена — при желании закрыть порт 8090 снаружи фаерволом (ufw), оставив доступ только NPM.
