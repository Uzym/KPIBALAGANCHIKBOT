"""Конфиг: переменные окружения приоритетнее файла .env (docker env_file)."""
import os

from config import Config


def _clear(monkeypatch) -> None:
    for key in ("VK_TOKEN", "VK_GROUP_ID", "TG_TOKEN", "TZ", "DB_PATH"):
        monkeypatch.delenv(key, raising=False)


def test_env_vars_fill_missing_file(tmp_path, monkeypatch):
    """В контейнере файла .env нет — конфиг собирается только из окружения."""
    _clear(monkeypatch)
    monkeypatch.setenv("VK_TOKEN", "env_vk")
    monkeypatch.setenv("VK_GROUP_ID", "241483738")
    monkeypatch.setenv("TG_TOKEN", "env_tg")
    cfg = Config.load(str(tmp_path / "нет-такого.env"))
    assert cfg.vk_token == "env_vk"
    assert cfg.vk_group_id == 241483738
    assert cfg.tg_token == "env_tg"
    assert cfg.validate_runtime() == []


def test_env_vars_override_file(tmp_path, monkeypatch):
    _clear(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "VK_TOKEN=file_vk\nVK_GROUP_ID=111\nTG_TOKEN=file_tg\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VK_TOKEN", "env_vk")
    monkeypatch.setenv("VK_GROUP_ID", "222")
    monkeypatch.setenv("TG_TOKEN", "env_tg")
    monkeypatch.setenv("PATH", "whatever")  # посторонние переменные не мешают
    cfg = Config.load(str(env_path))
    assert cfg.vk_token == "env_vk"
    assert cfg.vk_group_id == 222
    assert cfg.tg_token == "env_tg"


def test_empty_env_var_does_not_shadow_file(tmp_path, monkeypatch):
    _clear(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text("VK_TOKEN=file_vk\n", encoding="utf-8")
    monkeypatch.setenv("VK_TOKEN", "")
    cfg = Config.load(str(env_path))
    assert cfg.vk_token == "file_vk"


def test_local_file_still_works(tmp_path, monkeypatch):
    """Локальный запуск без docker: читается файл, окружение не обязательно."""
    _clear(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "VK_TOKEN=vk1\nVK_GROUP_ID=123\nTG_TOKEN=tg1\nTZ=Asia/Almaty\n",
        encoding="utf-8",
    )
    cfg = Config.load(str(env_path))
    assert cfg.vk_token == "vk1"
    assert cfg.vk_group_id == 123
    assert cfg.tg_token == "tg1"
    assert cfg.tz_name == "Asia/Almaty"
