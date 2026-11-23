# vk-tg-syncer · «Балаганчик»

Бот клуба КПИ «Уютный Балаганчик»: события с записью, опросы, взносы,
мост ВК ↔ Telegram, и веб-интерфейс (SPA на Svelte).

## Структура проекта

```
vk-tg-syncer/
├── main.py              # точка входа бота
├── app.py               # сборка приложения
├── config.py            # конфиг из .env
├── healthcheck.py       # Docker healthcheck
├── requirements.txt     # Python-зависимости
│
├── api/                 # слой API: клиенты VK/TG, хендлеры, outbox
├── bll/                 # бизнес-логика: события, RSVP, оплата, опросы
├── dal/                 # SQLite: модели, репозитории, миграции
├── web/                 # (устар.) NiceGUI-панель — заменяется frontend/
│
├── frontend/            # SPA на Svelte 5 + Vite
│   ├── src/
│   │   ├── pages/member/   # афиша, опросы, взнос, профиль, чат
│   │   ├── pages/admin/    # дашборд, события, люди, оплата
│   │   ├── components/     # MemberShell, AdminShell
│   │   └── lib/            # api.js (mock→REST), router.js
│   └── dist/               # собранная статика (npm run build)
│
├── scripts/             # setup.sh, deploy.sh, dev.sh, seed_demo.py
├── tests/               # pytest
├── prototypes/          # HTML-прототипы дизайна
├── docs/                # документация и планы
├── Dockerfile           # многоступенчатая сборка (Node + Python)
├── compose.yaml         # Docker Compose
└── Makefile             # шорткаты (make setup, make dev, make deploy)
```

## Быстрый старт

### Вариант 1: Локально

```bash
# 1. Установка (Python + Node + сборка)
bash scripts/setup.sh
# или: make setup

# 2. Заполнить .env
cp .env.example .env  # если ещё не создан
# → впиши VK_TOKEN, TG_TOKEN, ADMIN_VK_IDS и т.д.

# 3. Запуск
.venv/bin/python main.py    # бот
cd frontend && npm run dev  # фронт (http://localhost:5173)
# или обе сразу: make dev
```

### Вариант 2: Docker (VPS)

```bash
# 1. Клонировать и заполнить .env
git clone <repo> && cd vk-tg-syncer
cp .env.example .env && nano .env

# 2. Запустить
bash scripts/deploy.sh
# или: make deploy
# или: docker compose up -d --build
```

Dockerfile — многоступенчатый: сначала Node.js собирает фронтенд,
затем Python-образ копирует статику. Один контейнер, один процесс,
SQLite в volume `./data`.

## Частые команды

```bash
make help      # справка
make setup     # установка
make dev       # dev-режим (бот + фронт)
make test      # тесты
make build     # сборка фронтенда
make deploy    # деплой на VPS (Docker)
make clean     # почистить кеши
```

## Настройка платформ

### ВКонтакте

1. Создать сообщество → включить **Сообщения**.
2. **Управление → Сообщения → Настройки для бота**:
   - «Возможности ботов» — вкл
   - «Разрешать добавлять сообщество в беседы» — вкл
3. **Управление → Работа с API**:
   - Создать ключ доступа (права: сообщения, фото, документы)
   - Включить **Bots Long Poll API**
4. Добавить сообщество в беседы клуба (участник → добавить → сообщество),
   дать **администратора** → «Дать доступ ко всей переписке».

### Telegram

1. Создать группу, включить **Темы** (форум).
2. Создать бота через @BotFather → токен.
3. Добавить бота в группу **администратором**.
4. Узнать chat_id группы и id темы «События» (из ссылки или логов).

### .env

Все переменные — в [.env.example](.env.example). Обязательные:

| Переменная | Описание |
|---|---|
| `VK_TOKEN` | ключ доступа сообщества |
| `VK_GROUP_ID` | числовой id сообщества |
| `TG_TOKEN` | токен от @BotFather |
| `ADMIN_VK_IDS` | ваш user_id в ВК (через запятую) |
| `FEED_VK_PEER` | peer_id общей беседы (`2000000000 + chat_id`) |
| `FEED_TG_CHAT` | id TG-группы (`-100…`) |
| `FEED_TG_THREAD` | id темы «События» |

## Фронтенд

SPA на Svelte 5 + Vite. Дизайн-система «Афиша» (тёплая бумага, чернила, коралл).

```bash
cd frontend
npm install     # зависимости
npm run dev     # http://localhost:5173 (hot reload, /api → 8080)
npm run build   # → dist/ (статика для продакшена)
```

Сейчас `src/lib/api.js` работает на mock-данных. Для подключения к реальному
API — замени mock-функции на `fetch('/api/…')`.

Дизайн-прототипы: `prototypes/V1 Балаганчик-интерактивный-прототип.html`.

## Документация

- [docs/](docs/) — планы, архитектура, CJM, процессы
- [PLAN.md](PLAN.md) — входная точка в документацию

## Решение проблем

| Ошибка | Решение |
|---|---|
| `CERTIFICATE_VERIFY_FAILED` | Антивирус перехватывает HTTPS. `SSL_CA_BUNDLE` или `SSL_VERIFY=false` |
| `longpoll for this group is not enabled` | Управление → Работа с API → Bots Long Poll API → вкл |
| `Chat does not exist` (927) | Бот не добавлен в беседу / нет доступа к переписке |
| Bot id из ссылки `t.me/c/…` | Пиши в .env без `-100` — автонормализация добавит префикс |
