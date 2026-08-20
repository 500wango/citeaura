FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY requirements.txt ./
RUN pip wheel --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*
COPY api ./api
COPY engine ./engine
COPY web ./web
COPY alembic.ini requirements.txt ./
RUN addgroup --system citeaura && adduser --system --ingroup citeaura citeaura \
    && mkdir -p /app/work \
    && chown -R citeaura:citeaura /app
USER citeaura

FROM runtime AS api
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]

FROM runtime AS worker
CMD ["celery", "-A", "api.worker.celery_app", "worker", "--loglevel=INFO"]
