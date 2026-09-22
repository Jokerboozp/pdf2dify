from __future__ import annotations

import signal
import time

from .config import Settings
from .db import Database
from .pipeline import PipelineRunner


def run() -> None:
    settings = Settings.load()
    settings.ensure()
    db = Database(settings.database_path)
    db.init()
    runner = PipelineRunner(settings, db)
    stopping = False

    def stop(*_args):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    print(f"pdf2dify worker started; database={settings.database_path}", flush=True)
    while not stopping:
        job = db.claim_next_job()
        if job:
            runner.run(job)
        else:
            time.sleep(settings.poll_seconds)


if __name__ == "__main__":
    run()

