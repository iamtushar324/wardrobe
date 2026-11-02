"""Background worker: photo analysis, cutouts, proposals and OpenRouter image jobs.

    python -m wardrobe.worker

Runs next to the web process and shares the SQLite database. ChatGPT image jobs are not run here:
they go to the host Codex worker (worker/wardrobe-codex-worker.py) through /api/worker.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from typing import Callable

from . import db, ingest, jobs, studio  # noqa: F401  (handlers register on import)

log = logging.getLogger("wardrobe.worker")
TICK_EVERY = 20


def run(stop: Callable[[], bool]) -> None:
    db.migrate()
    last_tick = 0.0
    log.info("worker started")
    while not stop():
        try:
            if time.time() - last_tick > TICK_EVERY:
                studio.tick()
                last_tick = time.time()
            if not jobs.run_one():
                time.sleep(1.5)
        except Exception:
            log.exception("worker loop error")
            time.sleep(5)
    log.info("worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    run(stop.is_set)


if __name__ == "__main__":
    main()
