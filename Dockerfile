# ---------- Stage 1 : build des assets (CSS Tailwind + catalogues i18n) ----------
FROM python:3.12-slim AS assets

ARG TARGETARCH=amd64
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Binaire Tailwind standalone, architecture-dépendant (amd64 → x64, arm64 → arm64)
RUN case "$TARGETARCH" in \
        amd64) TW_ARCH=x64 ;; \
        arm64) TW_ARCH=arm64 ;; \
        *) echo "Architecture non prise en charge : $TARGETARCH" && exit 1 ;; \
    esac \
    && curl -sSL -o /usr/local/bin/tailwindcss \
        "https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-${TW_ARCH}" \
    && chmod +x /usr/local/bin/tailwindcss

RUN pip install --no-cache-dir babel

COPY app ./app
COPY babel.cfg ./

# CSS : scanne les templates via les @source de input.css
RUN tailwindcss -i app/static/src/input.css -o app/static/app.css --minify

# i18n : .po → .mo
RUN pybabel compile -d app/locale -D messages

# ---------- Stage 2 : runtime ----------
FROM python:3.12-slim

# iputils-ping : checks ICMP (cap_add NET_RAW requis, sinon GUIPAM_ENABLE_PING=false)
# curl : HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 1000 --create-home guipam

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --no-cache-dir . && pip cache purge || true

# Assets construits au stage 1
COPY --from=assets /build/app/static/app.css ./app/static/app.css
COPY --from=assets /build/app/locale ./app/locale

RUN mkdir -p /data && chown guipam:guipam /data /app
USER guipam

ENV GUIPAM_DB_PATH=/data/guipam.db \
    GUIPAM_HOST=0.0.0.0 \
    GUIPAM_PORT=8080

EXPOSE 8080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://localhost:${GUIPAM_PORT}/healthz" || exit 1

CMD ["python", "-m", "app.main"]
