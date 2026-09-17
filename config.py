"""Конфигурация из .env (см. .env.example)."""
from __future__ import annotations

import datetime as dt
import pathlib
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo


def _load_env_file(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    p = pathlib.Path(path)
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        env[key.strip()] = value
    return env


def _bool(v: str, default: bool = False) -> bool:
    if not v:
        return default
    return v.strip().lower() in ("1", "true", "yes", "да", "on")


@dataclass
class Config:
    # платформы
    vk_token: str = ""
    vk_group_id: int = 0
    vk_api_version: str = "5.199"
    tg_token: str = ""
    # хранение
    db_path: str = "data/kpibalaganchikbot.db"
    tz_name: str = "Europe/Moscow"
    # люди
    admin_vk_ids: list[int] = field(default_factory=list)  # дополнение к руководителям сообщества
    tech_admin_vk_id: int = 0           # тех-уведомления (запуск/падения) — только ему
    # поведение
    reminder_hours: list[float] = field(default_factory=lambda: [24.0, 2.0])
    autoclose_mode: str = "at_start"      # at_start | before_start
    autoclose_minutes: int = 120
    vk_strike_fallback: bool = False      # True — не юникод-зачёркивать в VK
    poll_max_options: int = 10
    announce_notice_ttl_hours: int = 48   # срок жизни уведомлений объявлений/изменений
    wall_log: bool = True                 # архив в сообщество: завершённые события/опросы и объявления постом на стену
    # сеть
    ssl_verify: bool = True
    ssl_ca_bundle: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def tz(self) -> dt.tzinfo:
        return ZoneInfo(self.tz_name)

    def validate_runtime(self) -> list[str]:
        errs = []
        if not self.vk_token or not self.vk_group_id:
            errs.append("Нужны VK_TOKEN и VK_GROUP_ID (id сообщества)")
        if not self.tg_token:
            errs.append("Нужен TG_TOKEN")
        return errs

    @classmethod
    def load(cls, env_path: str = ".env", overrides: dict | None = None) -> "Config":
        raw = _load_env_file(env_path)
        raw.update({k: str(v) for k, v in (overrides or {}).items()})

        def ints(key: str) -> list[int]:
            return [int(x) for x in raw.get(key, "").replace(";", ",").split(",") if x.strip()]

        def floats(key: str) -> list[float]:
            return [float(x) for x in raw.get(key, "").replace(";", ",").split(",") if x.strip()]

        return cls(
            vk_token=raw.get("VK_TOKEN", ""),
            vk_group_id=int(raw.get("VK_GROUP_ID", 0) or 0),
            vk_api_version=raw.get("VK_API_VERSION", "5.199"),
            tg_token=raw.get("TG_TOKEN", ""),
            db_path=raw.get("DB_PATH", "data/kpibalaganchikbot.db"),
            tz_name=raw.get("TZ", "Europe/Moscow"),
            admin_vk_ids=ints("ADMIN_VK_IDS"),
            tech_admin_vk_id=int(raw.get("TECH_ADMIN_VK_ID", 0) or 0),
            reminder_hours=floats("REMINDER_HOURS") or [24.0, 2.0],
            autoclose_mode=raw.get("AUTOCLOSE_MODE", "at_start"),
            autoclose_minutes=int(raw.get("AUTOCLOSE_MINUTES", 120) or 120),
            vk_strike_fallback=_bool(raw.get("VK_STRIKE_FALLBACK", ""), False),
            poll_max_options=int(raw.get("POLL_MAX_OPTIONS", 10) or 10),
            announce_notice_ttl_hours=int(raw.get("ANNOUNCE_NOTICE_TTL_HOURS", 48) or 48),
            wall_log=_bool(raw.get("VK_WALL_LOG", ""), True),
            ssl_verify=_bool(raw.get("SSL_VERIFY", ""), True),
            ssl_ca_bundle=raw.get("SSL_CA_BUNDLE", ""),
            warnings=[],
        )
