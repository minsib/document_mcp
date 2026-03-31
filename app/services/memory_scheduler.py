"""
Background scheduler for forgetting-curve maintenance.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.config import get_settings
from app.db.connection import get_db_context
from app.services.memory import MemoryService


logger = logging.getLogger(__name__)
settings = get_settings()


class MemoryMaintenanceScheduler:
    """Runs memory maintenance periodically inside the API process."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None

    def start(self) -> None:
        if not settings.ENABLE_MEMORY_MAINTENANCE_SCHEDULER:
            logger.info("Memory maintenance scheduler disabled by config")
            return
        if self._task and not self._task.done():
            return

        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="memory-maintenance-scheduler")
        logger.info(
            "Memory maintenance scheduler started with interval=%s minutes",
            settings.MEMORY_MAINTENANCE_INTERVAL_MINUTES,
        )

    async def stop(self) -> None:
        if not self._task:
            return

        if self._stop_event:
            self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            self._stop_event = None
        logger.info("Memory maintenance scheduler stopped")

    async def _run_loop(self) -> None:
        interval_seconds = max(settings.MEMORY_MAINTENANCE_INTERVAL_MINUTES, 1) * 60

        while True:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Memory maintenance scheduler iteration failed")

            assert self._stop_event is not None
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_seconds)
                return
            except asyncio.TimeoutError:
                continue

    async def _run_once(self) -> None:
        def _execute() -> dict[str, int]:
            with get_db_context() as db:
                return MemoryService(db).run_maintenance()

        result = await asyncio.to_thread(_execute)
        logger.info(
            "Memory maintenance completed: decayed=%s archived=%s",
            result.get("decayed", 0),
            result.get("archived", 0),
        )

