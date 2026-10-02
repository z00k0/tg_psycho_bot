# syntax=docker/dockerfile:1

FROM python:3.14.7-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends --yes build-essential=12.9 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install "poetry==2.2.1"

COPY pyproject.toml poetry.lock README.md ./
RUN poetry check --lock \
    && poetry install --only main --no-root

COPY app ./app
RUN poetry install --only main


FROM python:3.14.7-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TMPDIR=/tmp

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir --parents /app /data \
    && chown --recursive app:app /app /data

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv ./.venv
COPY --chown=app:app app ./app
COPY --chown=app:app pyproject.toml poetry.lock README.md psychological_dictionary.json ./

USER 10001:10001

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=2).read()"]

CMD ["tg-psyco", "serve"]
