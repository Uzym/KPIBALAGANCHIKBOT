# 20. Модель данных

> ⚠️ Исторический документ (v1–v2). Актуальная схема: [docs/60-v2-plan.md](60-v2-plan.md).

SQLite + SQLAlchemy, alembic-миграции. Все времени́е поля — UTC; отображение в
таймзоне клуба (конфиг).

## 1. Таблицы

### persons
| Поле | Тип | Примечание |
|---|---|---|
| id | PK | |
| display_name | text | «Аня К.» — как показывать в списках |
| created_at | ts | |

Единая личность для дедупликации голосов VK/TG.

### accounts
| Поле | Тип | Примечание |
|---|---|---|
| id | PK | |
| platform | enum(vk, tg) | |
| platform_user_id | bigint | UNIQUE(platform, platform_user_id) |
| person_id | FK persons, NULL | NULL — ещё не слинкован |
| display_name / username | text | кэш имён |
| tg_nick | text NULL | для vk-аккаунта: заявленный ник в TG |
| vk_nick | text NULL | для tg-аккаунта: заявленный ник/ссылка ВК |
| updated_at | ts | |

Линковка: `LinkingService` матчит `accounts.tg_nick` (vk-аккаунта) с
`accounts.username` (tg-аккаунта) и наоборот; при матче обоим проставляется общий
`person_id`, голоса пересчитываются. Конфликт (ник заявлен несколькими) — флаг
для админа, ручная `/связать`.

### subscriptions (только VK)
| Поле | Тип | Примечание |
|---|---|---|
| id | PK | |
| account_id | FK accounts UNIQUE | |
| status | enum(active, paused, blocked, guest) | guest — не в беседе; paused — вышел; blocked — заблокировал бота |
| send_announcements | bool default true | настройка «присылать объявления» |
| validated_at | ts | последняя проверка членства в беседе |

TG-подписок нет: контент в общий канал (тему «События»).

### chats
| Поле | Тип | Примечание |
|---|---|---|
| id | PK | |
| role | enum(bridge, feed_vk, feed_tg) | bridge — пара беседа↔тема; feed_vk — общая беседа; feed_tg — тема «События» |
| vk_peer_id | bigint NULL | 2000000000+chat_id |
| tg_chat_id, tg_thread_id | bigint NULL | для форум-тем |
| title | text | |

Пары для моста задаются двумя записями role=bridge с общим `pair_key`
(либо одной строкой с двумя ссылками — на реализации).

### events
| Поле | Тип | Примечание |
|---|---|---|
| id | PK | |
| title, place, note | text | place/note NULL |
| starts_at, ends_at | ts | ends_at может == starts_at+1ч (дефолт) |
| status | enum(draft, active, closed, cancelled, finished) | машина состояний в 40-processes |
| created_by | FK accounts | глава |
| closed_at / cancelled_at / finished_at / updated_at | ts NULL | |

### votes
| Поле | Тип | Примечание |
|---|---|---|
| id | PK | |
| event_id | FK events | UNIQUE(event_id, account_id) |
| account_id | FK accounts | |
| answer | enum(yes, maybe, no) | текущий ответ |
| prev_answer | enum NULL | для зачёркивания в прежнем списке |
| changes_count | int default 0 | сколько раз менял |
| updated_at | ts | время последней смены — показывается в записи |

Голос принадлежит аккаунту; в списках показывается через person (слияние после
линковки). Неслинкованные — метка платформы.

### event_posts
| Поле | Тип | Примечание |
|---|---|---|
| id | PK | |
| event_id | FK events | |
| kind | enum(dm_card, feed_record, topic_record, notice, announcement) | |
| platform | enum(vk, tg) | |
| chat_ref / account_id | — | адрес: ЛС конкретного подписчика или канал |
| message_id | bigint | для edit и reply-навигации |
| vm_hash | text | хеш последнего отправленного контента — не редактируем без изменений |
| status | enum(ok, edit_failed, deleted) | если edit падал — следующий раз шлём новым сообщением |

По reply на любое message_id из event_posts определяется событие
(«выбрать событие reply'ем»).

### announcements
| Поле | Тип |
|---|---|
| id, event_id FK, created_by FK, text, media JSON, post_refs JSON, created_at |

### outbox
| Поле | Тип | Примечание |
|---|---|---|
| id | PK | |
| op | enum(send, edit) | |
| platform | enum(vk, tg) | |
| chat_ref / account_id | — | адресат |
| view_model | JSON | что отрендерить |
| idempotency_key | text UNIQUE | защита от дублей |
| status | enum(pending, sending, done, failed) | |
| attempts, next_attempt_at | | ретраи с экспонентой |
| sent_message_id | bigint NULL | результат send — для последующих edit |

### bridge_map
`src_platform, src_chat, src_msg_id → dst_platform, dst_msg_id`
— чтобы зеркала не зацикливались и (этап 2) зеркалить edit/delete.

### reminders
`event_id, kind enum(day, h2), at, done` — материализованные точки напоминаний.

### media_cache
`file_hash PK, path, size, created_at` — дедупликация перекачки, чистка 7 дней.

## 2. Ключевые запросы

- Сводка события: `votes ⨝ accounts ⨝ persons WHERE event_id` + статус —
  собирается `SummaryBuilder`'ом на каждое изменение (событий немного, кэш не нужен).
- Фан-аут edit: `event_posts WHERE event_id AND kind IN (dm_card, feed_record, topic_record)`.
- Определение события по reply: `event_posts WHERE platform=? AND chat_ref=? AND message_id=?`.
- Outbox-воркеры: `SELECT … WHERE status=pending AND next_attempt_at<=now ORDER BY id LIMIT n`
  с `FOR UPDATE SKIP LOCKED`-аналогом (у SQLite — одна writer-сессия, воркеров не больше одной записи на тр-цию).

## 3. Целостность и миграции

- FK ON DELETE CASCADE для голосов/постов события.
- UNIQUE-ограничения из §1 — на уровне БД, не только кода.
- alembic: любая смена схемы через миграции; накат при старте.
- Бэкап: копия файла БД nightly + перед миграцией.
