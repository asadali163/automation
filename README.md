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
│   └── utils.py               # session-folder helpers, cleanup
├── tasks/                    # one subfolder per task = one tab
│   ├── base.py                 # the Task contract every module implements
│   └── file_merger/             # Task 1: zip upload -> merge into one file
│       ├── task.py                # declares the TASK object (title/icon/render)
│       ├── ui.py                   # Streamlit widgets for this tab
│       └── logic.py                 # pure Python logic (unit-testable, no Streamlit)
├── data/
│   ├── uploads/               # extracted uploads, per-session subfolders (gitignored)
│   └── outputs/                 # generated files offered for download (gitignored)
└── tests/                      # pytest, mirrors tasks/*/logic.py
```

### Why split `ui.py` from `logic.py`?

`logic.py` has zero Streamlit imports — it's plain Python you can unit test
with pytest and reuse outside the dashboard (a script, a notebook, later a
CLI). `ui.py` only wires Streamlit widgets to that logic. `task.py` just
registers the tab's metadata. This split is the convention every new task
should follow.

## Adding a new task

1. Copy `tasks/file_merger/` as a template, e.g. `tasks/my_new_task/`.
2. Write your logic in `logic.py` (no Streamlit), and a `render()` function
   in `ui.py` that builds the tab's UI and calls into `logic.py`.
3. In `task.py`, set `id`, `title`, `icon`, `order` (controls tab position —
   ascending, ties break alphabetically; existing tasks use 10, 20, ...
   leave gaps so you can slot new ones in between), and point `render` at
   your `ui.render` function.
4. Make sure `tasks/my_new_task/__init__.py` does `from .task import TASK`.
5. Done — `app.py` picks it up automatically on next run, no other file
   needs to change. Add `tests/test_my_new_task_logic.py` alongside it.

## Task 1: Merge Files

Upload a `.zip` containing (arbitrarily nested) folders of `.csv` /
`.xlsx` / `.xls` files. Every matching file, at any depth, is read into a
table and appended into a single merged CSV, with a
`--- Source: relative/path/to/file.csv ---` marker line before each
file's rows so you can always trace a row back to its origin.

Run just this task's tests:

```bash
pytest tests/test_file_merger_logic.py -v
```
