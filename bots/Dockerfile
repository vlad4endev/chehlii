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
RUN python -c "\
import os, pathlib, shutil, stat, urllib.request, sys;\
dest = pathlib.Path('/usr/local/bin/hysteria');\
vendored = pathlib.Path('/app/bots/hysteria');\
if vendored.is_file():\
    shutil.copy(vendored, dest);\
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH);\
    print('hysteria from bots/hysteria');\
    sys.exit(0);\
arch = os.environ.get('TARGETARCH') or 'amd64';\
name = 'hysteria-linux-arm64' if arch == 'arm64' else 'hysteria-linux-amd64';\
ver = '2.12.2';\
urls = [\
    f'https://github.com/apernet/hysteria/releases/download/app%2Fv{ver}/{name}',\
    f'https://download.hysteria.network/app/v{ver}/{name}',\
];\
err = None;\
\
for url in urls:\
    try:\
        urllib.request.urlretrieve(url, dest);\
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH);\
        print('hysteria', url);\
        sys.exit(0);\
    except Exception as e:\
        err = e;\
print('WARN hysteria download failed:', err, file=sys.stderr);\
"

# Долгоживущий поллер; внутри compose ходит в backend и redis по именам сервисов.
CMD ["python", "-m", "bots.run"]
