FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY bots/requirements.txt bots/requirements.txt
RUN pip install -r bots/requirements.txt

# xray-core: VLESS из админки → локальный SOCKS для Bot API.
# Бинарник кладётся в bots/xray (GitHub с RU VPS часто недоступен). См. .gitignore.
COPY bots/xray /usr/local/bin/xray
RUN chmod +x /usr/local/bin/xray

COPY bots/ bots/

# hysteria2-клиент: hy2:// из админки → тот же локальный SOCKS.
# Предпочтительно bots/hysteria (как xray). Иначе скачиваем при сборке.
ARG TARGETARCH=amd64
ENV TARGETARCH=${TARGETARCH}
RUN python bots/install_hysteria.py

# Долгоживущий поллер; внутри compose ходит в backend и redis по именам сервисов.
CMD ["python", "-m", "bots.run"]
