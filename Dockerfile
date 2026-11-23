# ═══════════════════════════════════════════════════════
# Многоступенчатая сборка: фронтенд → Python-бот
# ═══════════════════════════════════════════════════════

# ── Стадия 1: сборка фронтенда ──
FROM node:22-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --silent 2>/dev/null || npm install --silent
COPY frontend/ ./
RUN npm run build --silent

# ── Стадия 2: Python-бот + собранный фронт ──
FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# копируем собранный фронт
COPY --from=frontend-builder /build/dist/ /app/frontend/dist/

RUN useradd --create-home --uid 10001 bot \
    && mkdir -p /app/data \
    && chown -R bot:bot /app

USER bot
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

VOLUME ["/app/data"]

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python healthcheck.py

CMD ["python", "main.py"]
