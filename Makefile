# ═══════════════════════════════════════════════════════
# Makefile — шорткаты для частых задач
# ═══════════════════════════════════════════════════════

.PHONY: setup dev test build deploy clean help

help: ## Показать справку
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Первичная установка (Python + Node + сборка)
	bash scripts/setup.sh

dev: ## Dev-режим (бот + фронт, Ctrl+C — стоп)
	bash scripts/dev.sh

test: ## Прогнать тесты
	.venv/bin/python -m pytest tests/ -q

build: ## Собрать фронтенд (frontend/dist/)
	cd frontend && npm run build

deploy: ## Деплой на VPS (Docker Compose)
	bash scripts/deploy.sh --build

clean: ## Убрать кеши и сборки
	rm -rf __pycache__ .pytest_cache .mypy_cache frontend/dist
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true
