"""Pure logic for the Merge Files task — no Streamlit here, so it's easy to
unit test and to reuse from a script if needed.

Pipeline: extract_zip -> discover_files -> merge_files
"""
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from core.io import TABLE_EXTENSIONS, read_table

SUPPORTED_EXTENSIONS = TABLE_EXTENSIONS


@dataclass(frozen=True)
class DiscoveredFile:
    path: Path       # absolute path on disk
    rel_path: str     # path relative to the extraction root, used as the source label


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


def merge_files(files: List[DiscoveredFile]) -> Tuple[pd.DataFrame, Dict]:
    """Read every discovered file into one combined DataFrame (rows kept in
    file-discovery order; columns unioned if files differ), tagging each
    row's origin via a `source_file` column.

    This combined table is what downstream tasks (e.g. Deduplication)
    consume when you continue the pipeline instead of re-uploading. Use
    `to_marker_text()` to render the human-readable, per-file-annotated
    version for download.
    """
    frames = []
    errors = []

    for f in files:
        try:
            df = read_table(f.path)
        except Exception as exc:  # noqa: BLE001 - surface any read failure per-file
            errors.append(f"{f.rel_path}: {exc}")
            continue
        df = df.copy()
        df.insert(0, "source_file", f.rel_path)
        frames.append(df)

    combined = (
        pd.concat(frames, ignore_index=True, sort=False)
        if frames
        else pd.DataFrame(columns=["source_file"])
    )
    stats = {
        "files_found": len(files),
        "files_merged": len(files) - len(errors),
        "total_rows": len(combined),
        "errors": errors,
    }
    return combined, stats


def to_marker_text(combined: pd.DataFrame) -> str:
    """Render a combined DataFrame (as produced by `merge_files`) into the
    human-readable download format: one block per source file, each
    preceded by a `--- Source: <rel_path> ---` marker line.
    """
    if combined.empty:
        return ""
    blocks = []
    for source in combined["source_file"].unique():  # preserves first-seen order
        block_df = combined.loc[combined["source_file"] == source].drop(columns=["source_file"])
        blocks.append(f"--- Source: {source} ---\n{block_df.to_csv(index=False)}")
    return "\n".join(blocks)
