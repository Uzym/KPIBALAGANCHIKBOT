# 80. Развёртывание на VPS (Docker Compose)

Инструкция для продакшн-запуска бота на VPS. Один контейнер, SQLite в volume,
автоперезапуск, healthcheck, лог-ротация.

## 1. Требования

- VPS: 1 vCPU / 512 МБ RAM хватит (Ubuntu 22.04/24.04 или Debian 12).
- Docker + плагин compose v2.
- ⚠️ **Расположение VPS**: бот ходит в api.vk.com и api.telegram.org.
  Если VPS в регионе, где Telegram заблокирован, — либо возьми VPS за
  пределами региона, либо настрой HTTPS-прокси (см. §8).

## 2. Установка Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
docker compose version   # проверить плагин
```

## 3. Код и конфиг

```bash
mkdir -p /opt/club-bot && cd /opt/club-bot
git clone https://github.com/Uzym/KPIBALAGANCHIKBOT.git .
# первый клон по HTTPS спросит username + пароль; пароль = Personal Access Token:
# GitHub → Settings → Developer settings → Personal access tokens → classic, права repo.
# Репозиторий держи Private. .env и data/ в .gitignore — в гит не попадают.
git config credential.helper store   # запомнить токен, чтобы не вводить каждый раз
cp .env.example .env && nano .env
mkdir -p data && sudo chown -R 10001:10001 data
# ⚠️ важно: data/ нет в гите, docker создаст её от root, а контейнер пишет
# под uid 10001 — без chown бот не сможет открыть БД
```

Заполни `.env` (минимум):

```
VK_TOKEN=...          # ключ сообщества (права: сообщения, фото, документы, менеджер)
VK_GROUP_ID=...       # частное сообщество клуба
TG_TOKEN=...          # бот от @BotFather
ADMIN_VK_IDS=...      # необязательно: руководители сообщества и так админы
TECH_ADMIN_VK_ID=...  # кому слать «бот запущен»
TZ=Europe/Moscow
```

`.env` не попадёт в образ (`.dockerignore`), хранится только на VPS.

## 4. Запуск

```bash
docker compose up -d --build
docker compose logs -f        # смотреть старт: VK/TG long poll запущены
docker compose ps             # статус + healthcheck
```

Проверка работоспособности:

```bash
docker compose exec kpibalaganchikbot python integration_check.py --messaging
```

(отправит самоликвидирующиеся тест-сообщения админу; стены/канала в v5 нет).

## 5. Что внутри compose

- `./data:/app/data` — **SQLite и бэкапы на хосте** (переживают пересборку);
- `env_file: .env` — токены уходят в контейнер как **переменные окружения**
  (сам файл `.env` в образ не попадает — он в `.dockerignore`); `config.py`
  читает окружение с приоритетом над файлом, поэтому `docker compose config`
  должен показывать токены — если показывает, а бот ругается «Конфигурация
  неполная», пересоздай контейнер: `docker compose up -d --force-recreate`;
- `restart: unless-stopped` — поднимется после ребута VPS;
- HEALTHCHECK — раз в 60 с проверяет, что БД открывается;
- `stop_grace_period: 30s` — при остановке бот успевает сделать
  `wal_checkpoint(TRUNCATE)` и закрыть клиенты (консистентная БД);
- `read_only: true` + `tmpfs /tmp` — контейнер не пишет никуда, кроме volume;
- лог-ротация json-file: 10 МБ × 3 файла;
- non-root пользователь в контейнере.

## 6. Обновление

```bash
cd /opt/club-bot
git pull
docker compose up -d --build   # пересоберёт образ и перезапустит
docker compose logs -f --tail=50
```

Старый контейнер заменяется после успешной сборки; данные в `./data`
не трогаются. Откат: `git checkout <старый коммит> && docker compose up -d --build`.

## 7. Бэкап и восстановление

Бот сам делает бэкапы раз в сутки: `data/backups/kpibalaganchikbot-YYYYMMDD.db`
(ротация — 7 копий). Дополнительно копируй каталог с хоста:

```bash
# бэкап (желательно в момент, когда бот работает — WAL это позволяет)
tar czf /root/backups/kpibalaganchikbot-$(date +%F).tgz -C /opt/club-bot data
# восстановление
cd /opt/club-bot
docker compose stop
tar xzf /root/backups/kpibalaganchikbot-2026-09-18.tgz   # вернёт data/kpibalaganchikbot.db
docker compose start
```

## 8. Troubleshooting

| Симптом | Решение |
|---|---|
| Лог: `TG long poll: сеть/ошибка (Cannot connect to host api.telegram.org)` | Telegram недоступен с VPS (блокировка региона). Варианты: (а) VPS за пределами региона; (б) HTTPS-прокси: добавь в `.env` `HTTPS_PROXY=http://user:pass@host:port` (клиенты это поддерживают — `trust_env`), перезапусти: `docker compose up -d` |
| Лог: `CERTIFICATE_VERIFY_FAILED` | Антивирус/прокси подменяет HTTPS: `SSL_CA_BUNDLE=/path/ca.pem` (положи PEM в `data/` и укажи путь `/app/data/ca.pem`) или `SSL_VERIFY=false` временно |
| Лог: `VK error 100 ... Bots Long Poll API не включён` | В сообществе: Управление → Работа с API → Bots Long Poll API → Включить |
| Лог: `groups.isMember` отдаёт False у всех | Токен сообщества без права менеджер/сообщения — проверь права ключа |
| Бот не пишет в TG | Бот должен быть админом… в v5 TG-канала нет: проверь, что TG_TOKEN рабочий (`getMe` в логах старта) и слинковка задана в ВК |
| Диск растёт | Retention-чистка ежедневно + VACUUM по понедельникам + ротация бэкапов (7) + лог-ротация. Проверь: `du -sh /opt/club-bot/data` |
| `database is locked` | Один инстанс! Не запускай второй контейнер на тот же volume: `docker compose ps` должен показывать один kpibalaganchikbot |
| `unable to open database file` (healthcheck) | Права на `data/`: `sudo chown -R 10001:10001 data` (папку создал root при монтировании/клоне) |

## 9. Автозапуск и мониторинг

- `restart: unless-stopped` + Docker daemon в автозагрузке — после ребута VPS бот поднимется сам.
- О перезапусках узнаешь из сообщения «✅ Бот запущен» (`TECH_ADMIN_VK_ID`).
- Логи: `docker compose logs -f --tail=100`; heartbeat — раз в сутки бэкап-строка в логах.
- Алерты о падении контейнера (опционально): Uptime Kuma / healthchecks.io
  пинг по результату `docker compose ps --format '{{.Health}}'`.

## 10. Чек-лист перед «боем»

1. `docker compose ps` → healthy.
2. Логи старта: «VK long poll запущен», «TG long poll запущен (@твой_бот)»,
   «админы обновлены: N» (N ≥ 1).
3. `/start` боту в ВК от админа → меню админа.
4. `/событие Тест - завтра 19:00` → превью → публикация → карточка пришла.
5. `docker compose restart kpibalaganchikbot` → карточки/задания не потерялись
   (застрявшие «sending» восстанавливаются при старте).

## 11. Релиз новой фичи (и миграции БД)

База живёт в `./data` на хосте и **не теряется ни при каких пересборках** —
меняется только код в образе. Миграции применяются автоматически при старте
(`bootstrap`), каждая в своей версии схемы (`schema_version` в БД).

**Правило для разработчика:** любое изменение схемы =
1) правка `dal/models.py` (для свежих БД `create_all` сделает всё сам) +
2) функция-миграция в `dal/migrations.py` (версия `CURRENT_VERSION+1`,
**идемпотентная** — через `add_column_if_missing` / `create_index_if_missing`) +
3) поднятие `CURRENT_VERSION`.

**Процесс релиза на VPS:**

```bash
cd /opt/club-bot

# 1. Бэкап перед релизом (обязательно)
docker compose exec kpibalaganchikbot true 2>/dev/null   # бот жив?
tar czf /root/backups/pre-release-$(date +%F-%H%M).tgz data

# 2. Деплой
git pull
docker compose up -d --build

# 3. Проверить старт и миграции
docker compose logs --tail=50 | grep -E "БД готова|миграц|long poll|админы"
docker compose ps          # healthy?
```

Если в логах появилась строка «миграции БД применены: …» — схема обновлена
на месте, данные целы. Если миграция упала — бот не стартует (fail-fast),
данные не тронуты (идемпотентность гарантирует доделку после фикса):
смотри лог, чини миграцию, повторяй `git pull && docker compose up -d --build`.

**Откат:**

```bash
docker compose stop
git checkout <коммит до релиза>
tar xzf /root/backups/pre-release-<метка>.tgz   # вернуть data/ как было
docker compose up -d --build
```

Откат кода на старую версию совместим со схемой: миграции только добавляют
колонки/индексы, ничего не удаляют и не переименовывают — старая версия кода
продолжит работать на новой схеме.
