"""Точка входа: python main.py"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from app import App
from config import Config


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger("aiohttp.client").setLevel(logging.WARNING)


async def main() -> None:
    cfg = Config.load(".env")
    errors = cfg.validate_runtime()
    if errors:
        print("Конфигурация неполная:")
        for e in errors:
            print(f"  - {e}")
        print("См. .env.example и README.md")
        sys.exit(2)
    app = App(cfg)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass  # Windows: SIGTERM-хендлер не поддерживается — SIGINT хватит

    task = asyncio.create_task(app.run(), name="app")
    await stop.wait()
    logging.getLogger("main").info("получен сигнал остановки")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await app.shutdown()


if __name__ == "__main__":
    setup_logging()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.getLogger("main").info("остановлен")
