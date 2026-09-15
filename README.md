# Automation Project

A Streamlit dashboard for daily small automation tasks. Each task lives in
its own tab, and each tab is backed by its own self-contained module — so
the project grows by *adding folders*, not by editing existing code.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
streamlit run app.py
```

## How it's structured

```
Automation Project/
├── app.py                  # entry point — builds one tab per discovered task
├── config.py                # shared paths/constants (data dirs, etc.)
├── core/                    # framework code shared by all tasks
│   ├── task_registry.py      # auto-discovers tasks/* and turns them into tabs
│   ├── pipeline.py            # lets one task's output become the next task's input
│   ├── ui_helpers.py           # "continue from previous tab, or upload fresh" widget
│   ├── io.py                    # read_table(): CSV/Excel -> DataFrame, one place
│   ├── table_merge.py            # combine many tables into one + source-tagged text
│   └── utils.py                   # session-folder helpers, cleanup
├── tasks/                    # one subfolder per task = one tab
│   ├── base.py                 # the Task contract every module implements
│   ├── file_merger/             # Tab 1: zip upload -> merge into one file
│   ├── deduplication/             # Tab 2: multi-pass dedup
│   ├── geo_filter/                 # Tab 3: keep only rows inside a KML boundary
│   └── csv_merger/                  # Tab 4: upload several CSV/Excel files directly -> merge
│       ├── task.py                   # declares the TASK object (title/icon/order/render)
│       ├── ui.py                      # Streamlit widgets for this tab
│       └── logic.py                    # pure Python logic (unit-testable, no Streamlit)
├── data/
│   ├── uploads/               # extracted uploads, per-session subfolders (gitignored)
│   └── outputs/                 # generated files offered for download (gitignored)
└── tests/                      # pytest, mirrors tasks/*/logic.py and core/*.py
```

### Why split `ui.py` from `logic.py`?

`logic.py` has zero Streamlit imports — it's plain Python you can unit test
with pytest and reuse outside the dashboard (a script, a notebook, later a
CLI). `ui.py` only wires Streamlit widgets to that logic. `task.py` just
registers the tab's metadata. This split is the convention every new task
should follow.

### Chaining tabs together (`core/pipeline.py`)

Most of the time you'll want to run several tasks back-to-back on the same
data (e.g. merge -> dedup) without re-uploading at every step. Any task can
call `pipeline.publish(df, produced_by=..., task_title=...)` after it
finishes; any task can call `core.ui_helpers.pick_dataframe_source(key_prefix)`
to offer **"Continue from `<previous task>` output"** alongside a plain file
upload. It's all in-memory (`st.session_state`) — nothing written to disk,
and it resets when the browser tab/session ends. A task simply doesn't call
`pick_dataframe_source` if it should always start from a fresh upload (e.g.
Merge CSVs, by design, never continues from a previous tab).

## Adding a new task

1. Copy `tasks/file_merger/` as a template, e.g. `tasks/my_new_task/`.
2. Write your logic in `logic.py` (no Streamlit), and a `render()` function
   in `ui.py` that builds the tab's UI and calls into `logic.py`. If your
   task takes a table as input, use `core.ui_helpers.pick_dataframe_source`
   (chains from a previous tab) or `load_table_upload` (fresh upload only).
   If it produces a table others might want to continue from, call
   `core.pipeline.publish(...)` at the end.
3. In `task.py`, set `id`, `title`, `icon`, `order` (controls tab position —
   ascending, ties break alphabetically; existing tasks use 10/20/30/40 —
   leave gaps so you can slot new ones in between), and point `render` at
   your `ui.render` function.
4. Make sure `tasks/my_new_task/__init__.py` does `from .task import TASK`.
5. Done — `app.py` picks it up automatically on next run, no other file
   needs to change. Add `tests/test_my_new_task_logic.py` alongside it.

## Tab 1: Merge Files

Upload a `.zip` containing (arbitrarily nested) folders of `.csv` /
`.xlsx` / `.xls` files. Every matching file, at any depth, is read into a
table and combined into one, tagged with a `source_file` column. Download
gets the human-readable version — one block per source file, each preceded
by a `--- Source: relative/path/to/file.csv ---` marker line — while the
tagged table itself is offered to the next tab (e.g. Deduplication) so you
don't have to re-upload.

## Tab 2: Deduplication

Continue from a previous tab or upload a CSV/Excel file, then define one or
more dedup passes (pick which columns define "duplicate" for each pass).
Passes are cascading — pass *N* dedupes the *output* of pass *N-1* — and
keep the first occurrence within each duplicate group. Shows a per-pass
before/after row-count report and offers the result to the next tab.

## Tab 3: Geo Boundary Filter

Continue from a previous tab or upload a CSV/Excel file, plus a `.kml`
boundary file. Pick which columns hold latitude/longitude (not assumed to
be named "lat"/"lon" — auto-guessed as a default, but always overridable),
and only the rows whose point falls inside the KML boundary are kept.
Handles multiple/nested `<Polygon>` shapes and holes (`innerBoundaryIs`).

## Tab 4: Merge CSVs

Same idea as Merge Files, but for when you don't have a zip — upload two or
more `.csv`/`.xlsx`/`.xls` files directly. Shows a file-x-column presence
matrix up front so mismatched schemas are visible at a glance, then lets
you remove columns per file (handy for trimming an extra column out of one
file so it lines up with another) before merging — combined the same way
as Merge Files (source-tagged table + marker-annotated download). Always
starts from a fresh upload; it does not offer to continue from a previous
tab.

## Tests

```bash
pytest tests/ -v                                # everything
pytest tests/test_file_merger_logic.py -v        # one task
```
