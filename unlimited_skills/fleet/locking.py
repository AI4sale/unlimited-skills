"""One writer per local installation; contention never resets package state."""
from contextlib import contextmanager
import os


@contextmanager
def local_writer(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError('unsafe_fleet_writer_lock')
    with path.open('a+b') as handle:
        if path.stat().st_size == 0:
            handle.write(b'0');handle.flush()
        if os.name == 'nt':
            import msvcrt
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
