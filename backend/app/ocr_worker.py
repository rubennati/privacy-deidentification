"""OCR worker process entrypoint (ADR-0023 Phase 3).

Run with ``python -m app.ocr_worker``. This is the isolated ``ocr-worker`` Compose service command:
it initializes the shared SQLite job store, builds the runtime OCR adapter/PDF renderer, and polls
for pending ``ocr_text`` jobs until it receives ``SIGTERM``/``SIGINT`` (a graceful ``docker stop``),
finishing any in-flight job before exiting.
"""

from __future__ import annotations

import logging
import signal
import threading
from types import FrameType

from app.config import get_settings
from app.logging import configure_logging
from app.services.job_store import get_job_store
from app.services.ocr_worker import (
    build_worker,
    run_heartbeat_loop,
    run_worker_loop,
    worker_identity,
)

logger = logging.getLogger("app.ocr_worker")


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _request_stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("ocr worker shutdown requested", extra={"signal": signum})
        stop_event.set()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)


def main() -> None:
    """Configure logging, initialize the store, recover orphans, and poll until shutdown."""
    settings = get_settings()
    configure_logging(settings.log_level)

    store = get_job_store(settings)
    # Fails fast — and keeps the container restarting visibly — when the job database is
    # unavailable or its schema version is unsupported, instead of polling a store it must not
    # touch (see JobStoreIncompatibleError).
    store.initialize()
    worker = build_worker(settings, store)
    # A restart deterministically resolves whatever the previous life left claimed: requeue while
    # attempts remain, otherwise an explicit `interrupted` failure.
    worker.recover_on_startup()

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    heartbeat = threading.Thread(
        target=run_heartbeat_loop,
        kwargs={
            "store": store,
            "interval_seconds": settings.ocr_worker_poll_interval_seconds,
            "stop_event": stop_event,
            "worker_id": worker_identity(),
        },
        name="ocr-worker-heartbeat",
        daemon=True,
    )
    heartbeat.start()

    logger.info(
        "ocr worker started",
        extra={
            "poll_interval_seconds": settings.ocr_worker_poll_interval_seconds,
            "concurrency": settings.ocr_worker_concurrency,
            "max_attempts": settings.ocr_worker_max_attempts,
            "lease_seconds": settings.job_lease_seconds,
        },
    )
    run_worker_loop(
        worker,
        poll_interval_seconds=settings.ocr_worker_poll_interval_seconds,
        stop_event=stop_event,
    )
    heartbeat.join(timeout=5.0)
    logger.info("ocr worker stopped")


if __name__ == "__main__":
    main()
