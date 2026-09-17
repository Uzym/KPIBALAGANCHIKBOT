"""Healthcheck для Docker: БД открывается и отвечает на SELECT."""
import sys

from sqlalchemy import text

from config import Config
from dal.database import Database


def main() -> int:
    try:
        cfg = Config.load(".env")
        db = Database(cfg.db_path)
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("ok")
        return 0
    except Exception as e:  # noqa: BLE001
        print("fail:", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
