"""Small helpers shared by task modules (session-folder bookkeeping, etc.)."""
import shutil
import time
import uuid
from pathlib import Path


def short_id() -> str:
    """A short, URL/filename-safe unique id (e.g. for output filenames)."""
    return uuid.uuid4().hex[:8]


def new_session_dir(parent: Path) -> Path:
    """Create and return a fresh, uniquely-named scratch folder under `parent`."""
    session_dir = parent / short_id()
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def cleanup_old_dirs(parent: Path, max_age_hours: int = 24) -> None:
    """Delete subfolders of `parent` older than `max_age_hours`.

    Safe to call often (e.g. once at app startup) to stop `data/uploads`
    and `data/outputs` from growing forever.
    """
    if not parent.exists():
        return
    cutoff = time.time() - max_age_hours * 3600
    for child in parent.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
            elif child.is_file() and child.stat().st_mtime < cutoff:
                child.unlink(missing_ok=True)
        except OSError:
            pass
