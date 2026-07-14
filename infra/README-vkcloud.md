# Развёртывание на VK Cloud

Базовая структура `docker-compose.yml` сохраняется; при переносе на VK Cloud меняются только провайдеры хранилища и реестра образов (следствие из ТЗ v2.0).

| Компонент (локально) | VK Cloud |
|---|---|
| `postgres:16` (контейнер) | Управляемый PostgreSQL 16 (VK Cloud Databases) |
| `redis:7` (контейнер) | Управляемый Redis 7 (VK Cloud) |
| локальные volume файлов | VK Object Storage (S3-совместимый) — для статики фронтенда; файлы клиентов/макетов — Яндекс Диск (по ТЗ) |
| образ из `build:` | VK Container Registry (push из GitHub Actions) |
| — | Балансировщик + TLS (VK Cloud LB), домены лендинга и webhook'ов |

CI/CD (`.github/workflows/ci.yml` → отдельный `deploy.yml` в Спринте 1):
1. Сборка образов backend/фронтендов
2. `docker push` в VK Container Registry
3. Деплой на VK Cloud (compose на ВМ или k8s — уточняется с DevOps в Спринте 1)

Секреты (`.env`, JWT, токены ботов, ключи шлюзов, OAuth Яндекс Диска) — в секрет-хранилище VK Cloud / GitHub Actions Secrets, не в репозитории.
