#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# setup.sh — первичная установка на новой машине / VPS
# Использование: bash scripts/setup.sh
# ═══════════════════════════════════════════════════════
set -euo pipefail

echo "═══ Установка vk-tg-syncer ═══"
echo ""

# ── Python ──
echo "── Python ──"
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
echo "  Python OK (.venv)"

# ── Frontend ──
echo "── Frontend ──"
if command -v node &>/dev/null; then
    cd frontend
    [ -d node_modules ] || npm install --silent
    npm run build --silent
    echo "  Frontend OK (dist/ собран)"
    cd ..
else
    echo "  ⚠ Node.js не найден — фронт не собран (только бот)"
fi

# ── .env ──
echo "── Конфиг ──"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  Создан .env — ЗАПОЛНИ ТОКЕНЫ перед запуском!"
else
    echo "  .env уже существует"
fi

echo ""
echo "═══ Готово ═══"
echo "Запуск:       .venv/bin/python main.py"
echo "Тесты:        .venv/bin/python -m pytest tests/ -q"
echo "Докер:        docker compose up -d --build"
