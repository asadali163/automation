"""Global settings shared across all task modules.

Keep this file free of task-specific logic — it only defines paths and
constants that more than one task might need.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"   # scratch space for extracted uploads (per-session subfolders)
OUTPUTS_DIR = DATA_DIR / "outputs"   # generated files ready for download

for _dir in (UPLOADS_DIR, OUTPUTS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
