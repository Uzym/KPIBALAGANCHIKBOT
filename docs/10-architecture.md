# 10. Архитектура

> ⚠️ Исторический документ (v1–v2): беседа ВК, мост, темы TG удалены.
> Актуально: [docs/60-v2-plan.md](60-v2-plan.md) и [docs/70-vs-requirements.md](70-vs-requirements.md).

## 1. Общая форма: трёхзвенная архитектура

```
┌────────────────────────────────────────────────────────────────────┐
│ API (presentation) — платформенные адаптеры                         │
│   api/vk (vkbottle)         api/tg (aiogram 3)      api/common      │
│   приём апдейтов, DTO, рендеринг текстов/клавиатур, медиа, отправка │
└───────────────────────────────┬────────────────────────────────────┘
                                │ вызовы сервисов (in-process)
┌───────────────────────────────▼────────────────────────────────────┐
│ BLL (business logic) — доменные сервисы                             │
│   события, RSVP, публикации, профили/подписки, линковка, мост,      │
│   напоминания, медиа, админ, outbox-producer, планировщик           │
└───────────────────────────────┬────────────────────────────────────┘
                                │ репозитории (SQLAlchemy)
┌───────────────────────────────▼────────────────────────────────────┐
│ DAL (data access) — SQLite, модели, репозитории, alembic, бэкапы    │
└────────────────────────────────────────────────────────────────────┘
```

**Правила зависимостей** (проверяются на ревью):

- `api → bll → dal`; обратных зависимостей нет.
- BLL **не знает** платформ: операет платформонезависимыми моделями
  (`ViewModel` записи, `ChatRef`, `AccountRef`), а не «сообщениями ВК/TG».
- DAL **не содержит** бизнес-правил: только персистентность и запросы.
- Отправка сообщений — исключение из прямого вызова: BLL кладёт исходящие
  задания в **outbox** (таблица в DAL), а sender'ы в API их исполняют. Так BLL
  остаётся без платформенного кода, а рассылки переживают рестарт.

## 2. Слой API

### api/vk (vkbottle)

- Приём: `message_new` (ЛС + беседы), `message_event` (нажатия callback-кнопок
  в ЛС и беседах). Пропуск собственных сообщений (`from_id == -group_id`).
- Парсинг в DTO: `IncomingMessage`, `ButtonPress` (см. §6.1).
- Рендеринг: `ViewModel` → текст ВК + клавиатура. Особенности платформы:
  нет markdown (зачёркивание — юникод-комбинирование, spike), лимиты длины,
  `messages.send` / `messages.edit`.
- Медиа: скачивание вложений (фото по максимальному размеру, документы,
  голосовые), загрузка через upload-серверы ВК.
- Членство: `messages.getConversationMembers` для валидации подписок.

### api/tg (aiogram 3)

- Приём: `message` (ЛС бота, темы группы), `callback_query` (inline-кнопки в
  теме «События»). Свои сообщения не приходят — циклов нет со стороны TG.
- Рендеринг: `ViewModel` → MarkdownV2 (нативное `~~зачёркивание~~`, экранирование),
  inline-клавиатуры; постинг в тему через `message_thread_id`.
- Медиа: `getFile` (лимит 20 МБ), отправка всех типов.

### api/common

- `dto.py` — контракты между слоями.
- `senders.py` — воркеры outbox: забирают pending-задания, исполняют через
  адаптеры, соблюдают рейт-лимиты:
  - VK: ≤3 сообщения/с суммарно, ≤1/с одному peer; edit — с debounce ≥3 с;
  - TG: ≤25 сообщений/с суммарно, ≤1/с одному чату.
- Правило слоя: сервисные ответы (справка, «не понял команду») могут
  формироваться прямо в API; всё, что меняет доменное состояние — только через BLL.

## 3. Слой BLL — сервисы

| Сервис | Ответственность |
|---|---|
| `ProfileService` | Профили: подписка VK, настройка «присылать объявления», ники другой платформы |
| `SubscriptionService` | Статусы подписок VK (active/paused/blocked/guest), ревалидация членством в беседе, авто-подписка при голосе из беседы |
| `LinkingService` | Матчинг аккаунтов VK↔TG по заявленным никам; конфликты; ручная связка админом; слияние голосов после связки |
| `EventCommandParser` | Разбор `/событие Н - Д1 - Д2 - О` (форматы дат, дефолты, ошибки → переспрос) |
| `EventService` | Жизненный цикл: draft→active→closed/cancelled→finished; изменения полей; генерация задач на публикацию |
| `PublicationService` | Fan-out события по каналам (матрица в PLAN.md): ЛС VK, запись в беседе, запись в TG-теме; отчёты главе |
| `RsvpService` | Голоса, история изменений (prev_answer, время) для зачёркиваний, дедуп по person, проверки (статус события, членство) |
| `SummaryBuilder` | Сборка `ViewModel` записи (беседа/TG: списки + зачёркнутые) и карточки ЛС (чистые списки) |
| `AnnouncementService` | Объявления: реплаи на запись в беседе/TG-теме + ЛС VK-подписчикам с включённой настройкой |
| `ReminderService` | Напоминания (за сутки, за 2 ч): ЛС VK + реплай в TG-теме |
| `BridgeService` | Двусторонний мост: нормализация, форматирование «👤 [VK] Имя: …», перенос медиа, `bridge_map`, защита от циклов |
| `MediaService` | Кэш файлов (dedupe по hash), конверсия контрактов VK↔TG, лимиты и фолбэки (ссылка вместо файла) |
| `AdminService` | Команды главы, whitelist, `/связать`, `/подписчики`, `/события` |
| `scheduler_jobs` | Разовые/периодические задачи: авто-закрытие, авто-завершение, напоминания, ревалидация подписок, ретраи outbox, чистка кэша |

## 4. Слой DAL

- `models.py` — ORM (схема в 20-data-model.md).
- `repositories/` — по одному на агрегат: persons, accounts, subscriptions,
  events, votes, event_posts, announcements, outbox, bridge_map, reminders.
- `database.py` — engine, session-фабрика, Unit-of-Work (транзакция на use-case).
- `migrations/` — alembic. SQLite + WAL. Бэкап: копия файла + nightly-дамп.

## 5. Сквозные механизмы

- **Outbox** — единственный путь исходящих сообщений (кроме синхронных тостов на
  нажатия кнопок). Задание = операция (send/edit) + ViewModel + адрес; воркеры в
  API исполняют с лимитами и ретраями (экспонента, ночью — повтор неудачных).
- **Идемпотентность**: нажатие кнопки обрабатывается с ключом
  `(user, message, action)` — double-click не создаёт дублей; рассылки
  маркируются по `event_posts`, edit'ы по `(message_id, vm_hash)` — без изменения
  не редактируем.
- **Планировщик** (APScheduler): скан событий раз в минуту (закрытие/финиш),
  напоминания, ревалидация подписок (раз в сутки), чистка медиа-кэша (7 дней).
- **Логи**: структурные, с `event_id` / `account_id` / `outbox_id` — чтобы
  разбирать «почему Ане не пришло».
- **Конфиг** (pydantic-settings, .env): токены, chat_map (беседы ↔ темы),
  тема «События», whitelist главы, таймзона, точки напоминаний, правило
  авто-закрытия.

## 6. Потоки данных (ключевые последовательности)

### 6.1 Контракты DTO

```
IncomingMessage(platform, kind: dm|chat|topic, chat_ref, account_ref,
                text, media[], reply_to_ref, is_admin)
ButtonPress(platform, chat_ref, account_ref, message_ref, action, payload)
ViewModel(kind: dm_card|feed_record|notice|announcement|bridge,
          event_ref?, title, body_md, lists[], keyboard: [{action,label}], reply_to?)
OutboxJob(op: send|edit, platform, chat_ref, account_ref?, view_model,
          idempotency_key)
```

### 6.2 Создание и публикация события

```
Глава → api/vk: message_new «/событие …» (ЛС)
api/vk → EventCommandParser.parse() → EventService.create_draft() → DAL
api/vk ← превью ViewModel → [Опубликовать][Изменить][Отмена]
Глава: [Опубликовать] → api/vk: message_event → EventService.publish()
  ├─ DAL: event.status=active
  ├─ PublicationService → DAL outbox:
  │    N × dm_card (VK active-подписчики) + 1 × feed_record (беседа) + 1 × topic_record (TG-тема)
  ├─ scheduler: reminders + авто-закрытие + авто-финиш
  └─ отчёт главе (outbox) «Разослано N/M»
api/common senders исполняют outbox → адаптеры отправляют → event_posts фиксирует message_id
```

### 6.3 RSVP

```
Участник жмёт кнопку (VK ЛС | VK беседа | TG тема)
api → RsvpService.vote(event, account, answer)
  ├─ проверки: событие active, запись открыта, аккаунт валиден
  │    (голос из беседы = авто-подписка, если её не было)
  ├─ DAL: upsert votes (prev_answer, updated_at, changes_count)
  ├─ SummaryBuilder → feed_record VM (со зачёркиваниями) и dm_card VM (чистая)
  └─ DAL outbox: edit dm_card (все VK-карточки) + edit feed_record (беседа)
                 + edit topic_record (TG)
senders исполняют edit с debounce (VK ≥3 с на сообщение)
```

### 6.4 Изменение события

```
Глава: reply на сообщение события + /изменить поле=значение (или кнопки)
EventService.update()
  ├─ DAL: event поля; пересчёт таймеров
  ├─ edit всех dm_card / feed_record / topic_record (обновлённые поля)
  └─ отдельное сообщение «⚠️ Изменение события: …» (ЛС подписчикам, реплаи в беседе и TG-теме)
```

### 6.5 Объявление

```
Глава: reply на сообщение события + текст (и медиа)
AnnouncementService.publish()
  ├─ реплай на запись в беседе VK и в TG-теме
  └─ ЛС VK-подписчикам с profile.send_announcements=true
```

### 6.6 Мост

```
VK беседа#1: message_new (не бот, не зеркало по bridge_map)
  → BridgeService: нормализация (текст+медиа+reply) → MediaService при надобности
  → VM «👤 [VK] Имя: …» → outbox (tg topic#1) → bridge_map фиксирует пару id
TG тема#1: message → симметрично в беседу#1
Пропускаются: стикеры, сервисные, свои сообщения, сообщения бота (публикуются нативно)
```

### 6.7 Закрытие / отмена / завершение

```
Закрытие (глава кнопкой/командой | авто по правилу):
  edit записей: кнопки → «🔒 Запись закрыта»; реплай-уведомление в беседе/TG-теме
Отмена (глава): status=cancelled; edit записей (статусная строка) + отдельные
  реплаи «❌ Отменено» + ЛС подписчикам; таймеры сняты
Завершение (авто по ends_at): status=finished; финальная сводка — отдельный реплай
  в беседе и TG-теме + ЛС главе со списками
```

## 7. Структура проекта

```
kpibalaganchikbot/
├── pyproject.toml  .env.example  main.py  config.py
├── api/
│   ├── common/ (dto.py, senders.py)
│   ├── vk/     (bot.py, handlers.py, renderer.py, media.py)
│   └── tg/     (bot.py, handlers.py, renderer.py, media.py)
├── bll/
│   ├── profiles.py  subscriptions (в profiles)  linking.py
│   ├── events.py  publication.py  announcements.py
│   ├── rsvp.py  summary.py  reminders.py
│   ├── bridge.py  media.py  admin.py  scheduler_jobs.py
├── dal/
│   ├── models.py  database.py
│   ├── repositories/ (persons, accounts, subscriptions, events, votes,
│   │                  event_posts, announcements, outbox, bridge_map, reminders)
│   └── migrations/ (alembic)
└── docs/
```

Запуск: один процесс, asyncio; обе платформы long polling; публичный endpoint
не нужен. Деплой: постоянно включённый ПК (NSSM/Task Scheduler) или VPS
(docker-compose), автоперезапуск.

## 8. Отказоустойчивость

- Рестарт в любой момент: недоставленное лежит в outbox (pending), состояние — в БД.
- Ошибка доставки в ЛС (заблокировал бота) → подписка `blocked`, видно в
  `/подписчики`, глава может оповестить лично.
- Ретраи edit'ов: если edit упал (сообщение удалено пользователем) → пометка в
  `event_posts`, при следующем изменении — отправка нового сообщения вместо edit.
- Один процесс — узкое место: держим alive автоперезапуском; мониторинг —
  heartbeat-лог + (опция) уведомление главе при падении/restарте.
