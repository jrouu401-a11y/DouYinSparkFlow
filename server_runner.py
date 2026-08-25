"""Single-instance entry point for the VPS systemd service."""

import os
from contextlib import contextmanager

from core.tasks import runTasks


@contextmanager
def run_lock():
    lock_path = os.getenv("RUN_LOCK_FILE", "data/run.lock")
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            pass
        except BlockingIOError as exc:
            raise SystemExit("已有任务正在运行，跳过本次窗口") from exc
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except ImportError:
            pass
        handle.close()


if __name__ == "__main__":
    with run_lock():
        runTasks()
