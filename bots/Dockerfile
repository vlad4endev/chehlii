FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY bots/requirements.txt bots/requirements.txt
RUN pip install -r bots/requirements.txt

COPY bots/ bots/

# Долгоживущий поллер; внутри compose ходит в backend и redis по именам сервисов.
CMD ["python", "-m", "bots.run"]
