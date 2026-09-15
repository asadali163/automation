"""Pure logic for the Merge Files task — no Streamlit here, so it's easy to
unit test and to reuse from a script if needed.

Pipeline: extract_zip -> discover_files -> merge_files

The actual "combine tables into one DataFrame" / "render back to marker
text" logic lives in `core.table_merge`, shared with the Merge CSVs task —
this module's own job is just turning a zip's extracted contents into a
list of source files.
"""
import zipfile
from pathlib import Path
from typing import List

from core.io import TABLE_EXTENSIONS
from core.table_merge import SourceFile, combine_tables, to_marker_text  # noqa: F401 - re-exported

SUPPORTED_EXTENSIONS = TABLE_EXTENSIONS
DiscoveredFile = SourceFile  # kept as an alias for readability in this task's context
merge_files = combine_tables  # kept as an alias: this task's name for "combine + tag by source"


def extract_zip(zip_path: Path, extract_to: Path) -> Path:
    """Extract `zip_path` into `extract_to` (created if missing), preserving
    the nested folder structure. Returns `extract_to`.
    """
    extract_to.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            # guard against zip-slip (paths that escape extract_to)
            target = (extract_to / member.filename).resolve()
            if not str(target).startswith(str(extract_to.resolve())):
                raise ValueError(f"Unsafe path in zip: {member.filename}")
        zf.extractall(extract_to)
    return extract_to


def discover_files(root: Path, extensions=SUPPORTED_EXTENSIONS) -> List[DiscoveredFile]:
    """Recursively find every CSV/Excel file under `root`, however deeply
    nested, skipping hidden files and Excel lock files (~$...).
    """
    files = []
    for p in sorted(root.rglob("*")):
        if (
            p.is_file()
            and p.suffix.lower() in extensions
            and not p.name.startswith("~$")
            and not p.name.startswith(".")
        ):
            files.append(DiscoveredFile(path=p, rel_path=str(p.relative_to(root))))
    return files
