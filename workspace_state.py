"""Shared workspace lock and reset generation for local app processes."""
from contextlib import contextmanager
from functools import wraps
import json
import threading
from filelock import FileLock

_locks = {}
_mutex = threading.Lock()


@contextmanager
def guard():
    import local_store as store
    root = store.DATA_DIR.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _mutex:
        lock = _locks.setdefault(str(root), FileLock(str(root / '.workspace.lock'), timeout=60))
    with lock:
        yield


def guarded(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        with guard():
            return fn(*args, **kwargs)
    return call


def generation():
    import local_store as store
    path = store.DATA_DIR / 'workspace_generation.json'
    with guard():
        return json.loads(path.read_text(encoding='utf-8'))['id'] if path.exists() else 'initial'


def check_generation(expected):
    if expected is not None and expected != generation():
        raise ValueError('The workspace was reset. Reload this student and prepare a new draft.')
