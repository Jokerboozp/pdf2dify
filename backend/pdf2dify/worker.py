from __future__ import annotations

import signal
import time
from filelock import FileLock, Timeout

from .config import Settings
from .db import Database
from .pipeline import PipelineRunner


def run() -> None:
    settings = Settings.load()
    settings.ensure()
    db = Database(settings.database_path)
    db.init()
    lock = FileLock(str(settings.data_dir / "worker.lock"), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        raise SystemExit("pdf2dify Worker 已在运行")
    recovered = db.recover_interrupted_jobs()
    runner = PipelineRunner(settings, db)
    stopping = False

    def stop(*_args):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    print(f"pdf2dify worker started; database={settings.database_path}; recovered={len(recovered)}", flush=True)
    try:
        while not stopping:
            job = db.claim_next_job()
            if job:
                runner.run(job)
            else:
                time.sleep(settings.poll_seconds)
    finally:
        lock.release()


if __name__ == "__main__":
    run()
