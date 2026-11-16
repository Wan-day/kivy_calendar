"""Background worker that periodically drains the retry queue."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from sync.service import SyncService

logger = logging.getLogger(__name__)


async def run_retry_worker(service: SyncService, interval_seconds: float) -> None:
    """Replay due retries every ``interval_seconds`` until cancelled.

    Failures are logged and never escape the loop, so one bad cycle cannot stop
    later cycles or crash the application.
    """
    while True:
        try:
            result = await asyncio.to_thread(service.process_due_retries)
            if result.error is not None:
                logger.warning("retry cycle failed: %s", result.error.message)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the worker must never die
            logger.exception("retry worker cycle raised")
        await asyncio.sleep(interval_seconds)


def start_retry_worker(
    service: SyncService,
    interval_seconds: float,
) -> asyncio.Task[None] | None:
    """Start the worker task, or return ``None`` when the interval disables it."""
    if interval_seconds <= 0:
        return None
    return asyncio.create_task(run_retry_worker(service, interval_seconds))


async def stop_retry_worker(task: asyncio.Task[None] | None) -> None:
    """Cancel the worker task and wait for it to finish."""
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
