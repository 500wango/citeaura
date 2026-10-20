FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY requirements.txt requirements.lock ./
RUN pip wheel --wheel-dir /wheels -r requirements.lock

FROM python:3.12-slim AS runtime

ARG GIT_SHA=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    CITEAURA_SOURCE_REVISION=${GIT_SHA}
WORKDIR /app
# pg_dump 供 scripts/migrate_db.py 在自动迁移前做整库备份。
# 必须与 docker-compose.prod.yml 的 POSTGRES_MAJOR（默认 18）同版本：
# pg_dump 拒绝备份更高版本的服务器，版本落后会让自动迁移在备份阶段中止。
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*
COPY api ./api
COPY engine ./engine
COPY web ./web
COPY alembic.ini requirements.txt requirements.lock ./
RUN addgroup --system citeaura && adduser --system --ingroup citeaura citeaura \
    && mkdir -p /app/work \
    && chown -R citeaura:citeaura /app
USER citeaura

FROM runtime AS api
COPY --chown=citeaura:citeaura scripts ./scripts
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready')"
ENTRYPOINT ["sh", "/app/scripts/docker-entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS:-127.0.0.1,172.16.0.0/12}\""]

FROM runtime AS worker
CMD ["celery", "-A", "api.worker.celery_app", "worker", "--loglevel=INFO", "--pool=prefork"]
