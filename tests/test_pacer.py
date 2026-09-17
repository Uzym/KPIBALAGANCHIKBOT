"""Тест Pacer: wait должен возвращаться сразу при первом вызове (регрессия Windows)."""
import asyncio
import time as time_mod

from api.senders import Pacer


def test_pacer_first_call_fast():
    async def go() -> float:
        p = Pacer(min_global=0.05, min_per_key=0.1)
        t0 = time_mod.monotonic()
        await p.wait(("vk", "x"))       # первый вызов — без ожидания
        first = time_mod.monotonic() - t0
        assert first < 0.3, f"первый вызов занял {first:.2f}s — pacer завис"
        await p.wait(("vk", "x"))       # повтор по тому же ключу — ждёт min_per_key
        return time_mod.monotonic() - t0

    elapsed = asyncio.run(go())
    assert elapsed >= 0.08, "повторный вызов должен выдержать интервал"
    assert elapsed < 2.0


def test_pacer_different_keys():
    async def go():
        p = Pacer(min_global=0.01, min_per_key=10.0)
        t0 = time_mod.monotonic()
        await p.wait(("vk", "a"))
        await p.wait(("vk", "b"))  # другой ключ — интервал per_key не мешает
        assert time_mod.monotonic() - t0 < 0.5

    asyncio.run(go())
