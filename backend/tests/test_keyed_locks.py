"""A keyed async lock serialises renders that write the same experiment's files."""

from __future__ import annotations

import asyncio

from flir_research_interface.concurrency import KeyedLocks


def test_same_key_is_mutually_exclusive() -> None:
    async def run() -> int:
        locks = KeyedLocks()
        active = 0
        max_active = 0

        async def section() -> None:
            nonlocal active, max_active
            async with locks.get("run"):
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.02)  # hold the section so an overlap would show
                active -= 1

        await asyncio.gather(*(section() for _ in range(4)))
        return max_active

    assert asyncio.run(run()) == 1  # sections for the same key never overlap


def test_different_keys_run_in_parallel() -> None:
    async def run() -> list[str]:
        locks = KeyedLocks()
        order: list[str] = []

        async def hold(key: str, first: bool) -> None:
            async with locks.get(key):
                order.append(f"enter-{key}")
                await asyncio.sleep(0.05 if first else 0.0)
                order.append(f"exit-{key}")

        await asyncio.gather(hold("a", True), hold("b", False))
        return order

    order = asyncio.run(run())
    assert order.index("enter-b") < order.index("exit-a")  # b did not wait for a


def test_get_returns_the_same_lock_per_key() -> None:
    locks = KeyedLocks()
    assert locks.get("x") is locks.get("x")
    assert locks.get("x") is not locks.get("y")
