#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# dev.sh — запуск dev-окружения (бот + фронт одновременно)
# Использование: bash scripts/dev.sh
# ═══════════════════════════════════════════════════════
set -euo pipefail
cd "$(dirname "$0")/.."

PIDS=()

cleanup() {
    echo ""
    echo "── Остановка ──"
    for pid in "${PIDS[@]:-}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    echo "Готово."
}
trap cleanup EXIT INT TERM

# ── Бот ──
echo "── Запуск бота (main.py) ──"
.venv/bin/python main.py &
PIDS+=($!)

# ── Фронт (vite dev) ──
if command -v node &>/dev/null && [ -d frontend ]; then
    echo "── Запуск фронтенда (vite) ──"
    echo "   http://localhost:5173 (проксирует /api → 8080)"
    cd frontend && npx vite --clearScreen false &
    PIDS+=($!)
    cd ..
fi

echo ""
echo "═══ Dev-режим запущен ═══"
echo "  Бот:       http://localhost:8080"
echo "  Фронт:     http://localhost:5173"
echo "  Ctrl+C — остановить всё"
echo ""

wait
