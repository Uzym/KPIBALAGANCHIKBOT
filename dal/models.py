"""DAL: ORM-модели (см. docs/60-v2-plan.md, п. 10)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .database import now_utc


class Base(DeclarativeBase):
    pass


class Content(Base):
    """Сквозной id всех карточек (события + опросы — одна нумерация)."""
    __tablename__ = "contents"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # event | poll
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class Person(Base):
    __tablename__ = "persons"
    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc)


class Account(Base):
    """Аккаунт платформы; person_id связывает VK и TG записи одного человека."""
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("platform", "platform_user_id", name="uq_account_platform"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(8))  # vk | tg
    platform_user_id: Mapped[int] = mapped_column(BigInteger)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id"), nullable=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    username: Mapped[str | None] = mapped_column(String(200))  # tg @username / vk domain
    tg_nick: Mapped[str | None] = mapped_column(String(200))  # заявленный ник в TG (у vk-аккаунта)
    vk_nick: Mapped[str | None] = mapped_column(String(200))  # заявленный id ВК (у tg-аккаунта)
    mode: Mapped[str] = mapped_column(String(8), default="member")  # admin | member (режим админа)
    tg_dm_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class Subscription(Base):
    """Подписка на события/опросы. Только для VK (TG получает по линковке)."""
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|paused|blocked|stopped
    send_announcements: Mapped[bool] = mapped_column(Boolean, default=True)
    validated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)  # последняя проверка isMember
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(ForeignKey("contents.id"), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime)
    ends_at: Mapped[dt.datetime] = mapped_column(DateTime)
    place: Mapped[str | None] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|active|closed|cancelled|finished
    created_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_closed: Mapped[bool] = mapped_column(Boolean, default=False)  # авто-закрытие уже сработало
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("event_id", "account_id", name="uq_vote_event_account"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    answer: Mapped[str] = mapped_column(String(8))  # yes | maybe | no
    prev_answer: Mapped[str | None] = mapped_column(String(8))
    changes_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(ForeignKey("contents.id"), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    options: Mapped[str] = mapped_column(Text)  # JSON [{idx, text}]
    multichoice: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|active|closed|cancelled
    closes_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_closed: Mapped[bool] = mapped_column(Boolean, default=False)  # авто-закрытие по сроку сработало
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class PollVote(Base):
    """Строка = выбор варианта. active=False — выбор снят (зачёркивание)."""
    __tablename__ = "poll_votes"
    __table_args__ = (UniqueConstraint("poll_id", "account_id", "option_id", name="uq_poll_vote"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    option_id: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    changes_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class Post(Base):
    """Отправленное сообщение контента: пост стены/канала, карточка ЛС, уведомление."""
    __tablename__ = "posts"
    __table_args__ = (
        Index(
            "uq_post_dm", "content_type", "content_id", "kind", "account_id",
            unique=True, sqlite_where=text("account_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    content_type: Mapped[str] = mapped_column(String(16))  # event | poll | announcement
    content_id: Mapped[int] = mapped_column(BigInteger)    # id из contents / announcements
    kind: Mapped[str] = mapped_column(String(16))  # dm_card | dm_notice
    platform: Mapped[str] = mapped_column(String(8))  # vk | tg
    chat_id: Mapped[str] = mapped_column(String(64))  # vk peer / tg chat; для стены — "-<group_id>"
    thread_id: Mapped[int | None] = mapped_column(BigInteger)  # не используется (канал), зарезервировано
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))  # для dm_*
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    vm_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|ok|deleted|blocked
    conflict: Mapped[bool] = mapped_column(Boolean, default=False)  # невалидная правка стены
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc)


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    content_type: Mapped[str] = mapped_column(String(16))  # event | poll | global
    content_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # NULL для global
    created_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    text: Mapped[str] = mapped_column(Text)
    media: Mapped[str | None] = mapped_column(Text)  # JSON
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc)


class OutboxJob(Base):
    """Исходящее сообщение: отправка через сендеры API-слоя, с ретраями."""
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    op: Mapped[str] = mapped_column(String(8))  # send | edit | delete
    platform: Mapped[str] = mapped_column(String(8))
    chat_id: Mapped[str] = mapped_column(String(64))
    thread_id: Mapped[int | None] = mapped_column(BigInteger)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"))
    view_model: Mapped[str] = mapped_column(Text)  # JSON OutMessageVM
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|sending|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc)
    sent_message_id: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc)


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    content_type: Mapped[str] = mapped_column(String(16))  # event | poll
    content_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(16))  # h24 | h2 (по факту: за N часов)
    at: Mapped[dt.datetime] = mapped_column(DateTime)
    done: Mapped[bool] = mapped_column(Boolean, default=False)


class Appeal(Base):
    """Обращение участника к админам (персист — ответы работают после рестарта)."""
    __tablename__ = "appeals"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(8))  # vk | tg
    member_id: Mapped[int] = mapped_column(BigInteger)
    member_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc)


class AppealMessage(Base):
    """Пересылка обращения конкретному админу (для ответов и пометки «отвечено»)."""
    __tablename__ = "appeal_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    appeal_id: Mapped[int] = mapped_column(ForeignKey("appeals.id"))
    admin_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)  # cmid пересылки в ЛС админа
    answered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc)


class Attendance(Base):
    """Отметка «кто реально пришёл» (для админа, по завершённому событию)."""
    __tablename__ = "attendances"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    person_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id"), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_utc)


class SchemaVersion(Base):
    """Версия схемы БД (одна строка) — для последовательных миграций."""
    __tablename__ = "schema_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
