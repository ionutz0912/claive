"""claive/lib/lock.py — File locking helpers using fcntl.flock."""

import fcntl
import json
import os
from contextlib import contextmanager


@contextmanager
def file_lock(path, mode="r+"):
    """Context manager for exclusive file locking.

    Creates the file if it doesn't exist (for 'r+' mode, falls back to 'w+').
    Yields the file handle with an exclusive lock held.
    """
    if mode == "r+" and not os.path.exists(path):
        # Create with restricted permissions
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)

    f = open(path, mode)
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield f
    finally:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        f.close()


def read_json_locked(path, default=None):
    """Read a JSON file with shared lock. Returns default if file missing/empty."""
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with file_lock(path, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            content = f.read().strip()
            return json.loads(content) if content else (default if default is not None else {})
    except (json.JSONDecodeError, IOError):
        return default if default is not None else {}


def write_json_locked(path, data):
    """Write a JSON file with exclusive lock. Sets chmod 600."""
    with file_lock(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.chmod(path, 0o600)
