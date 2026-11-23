#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# deploy.sh — деплой на VPS через Docker Compose
# Использование: bash scripts/deploy.sh [--build]
# ═══════════════════════════════════════════════════════
set -euo pipefail
cd "$(dirname "$0")/.."

echo "═══ Деплой vk-tg-syncer ═══"

# ── Проверка .env ──
if [ ! -f .env ]; then
    echo "ОШИБКА: .env не найден. Скопируй .env.example → .env и заполни."
    exit 1
fi

# ── Сборка фронтенда (если Node есть) ──
if command -v node &>/dev/null && [ -d frontend ]; then
    echo "── Сборка фронтенда ──"
    cd frontend && npm run build --silent && cd ..
    echo "  dist/ обновлён"
fi

# ── Docker ──
echo "── Docker Compose ──"
if [ "${1:-}" = "--build" ]; then
    docker compose up -d --build
else
    docker compose up -d
fi

echo ""
echo "── Статус ──"
docker compose ps
echo ""
echo "── Логи (последние 20 строк) ──"
docker compose logs --tail 20
echo ""
echo "═══ Деплой завершён ═══"
