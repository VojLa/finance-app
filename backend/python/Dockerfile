FROM python:3.12.10-slim

WORKDIR /app/backend/python

ENV UV_PROJECT_ENVIRONMENT=/opt/finance-app-venv \
    PATH="/opt/finance-app-venv/bin:${PATH}"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl --fail --silent --show-error \
        --output /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install --yes --no-install-recommends postgresql-client-16 \
    && pip install --no-cache-dir uv==0.10.6 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/python/pyproject.toml backend/python/uv.lock backend/python/.python-version ./
RUN uv sync --frozen --extra dev --no-install-project

COPY package.json /app/package.json
COPY prisma/migrations /app/prisma/migrations
COPY .github/workflows /app/.github/workflows
COPY backend/python ./
RUN uv sync --frozen --extra dev

EXPOSE 8010

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--reload"]
