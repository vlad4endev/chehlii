FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY bots/requirements.txt bots/requirements.txt
RUN pip install -r bots/requirements.txt

# xray-core: VLESS-ключ из админки превращается в локальный SOCKS для Bot API.
ARG XRAY_VERSION=26.1.23
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip \
 && arch="$(uname -m)" \
 && if [ "$arch" = "aarch64" ]; then asset="Xray-linux-arm64-v8a.zip"; else asset="Xray-linux-64.zip"; fi \
 && curl -fsSL "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/${asset}" -o /tmp/xray.zip \
 && unzip -q /tmp/xray.zip xray -d /usr/local/bin \
 && chmod +x /usr/local/bin/xray \
 && rm -f /tmp/xray.zip \
 && apt-get purge -y curl unzip && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

COPY bots/ bots/

# Долгоживущий поллер; внутри compose ходит в backend и redis по именам сервисов.
CMD ["python", "-m", "bots.run"]
