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
│   ├── geo_filter/                  # Tab 3: keep only rows inside a KML boundary
│   ├── csv_merger/                    # Tab 4: upload several CSV/Excel files directly -> merge
│   ├── geocoding/                       # disabled — see note below, not currently a tab
│   └── csv_to_excel/                      # Tab 5: upload a .csv -> download as .xlsx
│       ├── task.py                          # declares the TASK object (title/icon/order/render)
│       ├── ui.py                             # Streamlit widgets for this tab
│       └── logic.py                           # pure Python logic (unit-testable, no Streamlit)
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
   ascending, ties break alphabetically; existing tasks use 10/20/30/40/60 —
   leave gaps so you can slot new ones in between), and point `render` at
   your `ui.render` function.
4. Make sure `tasks/my_new_task/__init__.py` does `from .task import TASK`.
5. Done — `app.py` picks it up automatically on next run, no other file
   needs to change. Add `tests/test_my_new_task_logic.py` alongside it.

**Disabling a tab without deleting it:** comment out the `from .task import
TASK` line in that task's `__init__.py` (see `tasks/geocoding/__init__.py`
for the pattern). The registry only turns a `tasks/*` subfolder into a tab
if it exposes a `TASK` object, so this hides it with zero risk to the
task's actual code — uncomment to bring it back.

## Tab 1: Merge Files

Upload a `.zip` containing (arbitrarily nested) folders of `.csv` /
`.xlsx` / `.xls` files. Every matching file, at any depth, is read into a
table and combined into one flat table, tagged with a `source_file` column
on every row (so you can trace where the data came from without breaking
Excel filters/pivots/sorting the way an inline marker row would). Offered
to the next tab (e.g. Deduplication) so you don't have to re-upload.

## Tab 2: Deduplication

Continue from a previous tab or upload a CSV/Excel file, then define one or
more dedup passes (pick which columns define "duplicate" for each pass).
Passes are cascading — pass *N* dedupes the *output* of pass *N-1* — and
keep the first occurrence within each duplicate group. Shows a per-pass
before/after row-count report and offers the result to the next tab.

## Tab 3: Geo Boundary Filter

Continue from a previous tab or upload a CSV/Excel file, plus a `.kml`
boundary file. Pick which columns hold latitude/longitude (not assumed to
be named "lat"/"lon" — auto-guessed as a default, but always overridable).
Handles multiple/nested `<Polygon>` shapes and holes (`innerBoundaryIs`).

Every row gets a `boundary_status` of `inbound` (inside the boundary) or
`outbound` (outside it, or its coordinates were missing/invalid) — shown
both as a map (`pydeck`, ships with Streamlit — boundary polygon plus every
plottable shop colored green/red by status) and as a table. Three separate
downloads: the full processed table (all rows + `boundary_status`), inbound
only, and outbound only.

Pick which columns to show, then **click a shop on the map** for a details
panel below it (hover gives a quick preview tooltip first). Uses Streamlit's
native `st.pydeck_chart(..., on_select="rerun")` selection API — no extra
dependency.

## Tab 4: Merge CSVs

Same idea as Merge Files, but for when you don't have a zip — upload two or
more `.csv`/`.xlsx`/`.xls` files directly. Shows a file-x-column presence
matrix up front so mismatched schemas are visible at a glance, then lets
you remove columns per file (handy for trimming an extra column out of one
file so it lines up with another) before merging — combined the same way
as Merge Files (one flat table, `source_file` column on every row). Always
starts from a fresh upload; it does not offer to continue from a previous
tab.

## Tab 5: CSV to Excel

Upload a `.csv` file and download it back as an `.xlsx` file — pure format
conversion, no other changes to the data.

## Geocoding (currently disabled)

Not shown as a tab right now — commented out in `tasks/geocoding/__init__.py`
(see "Disabling a tab without deleting it" above), code fully intact.

When enabled: continue from a previous tab or upload a CSV/Excel file, then
pick 1 or 2 columns that hold the address (e.g. "street" + "city"). Adds
`latitude`, `longitude`, `geocode_status`, `geocode_source` and
`geocode_query` columns.

Two providers are tried per address, in order:

1. **Nominatim** (OpenStreetMap) — free, no key, rate-limited to ~1
   lookup/second. Rather than querying the address once, it walks a ladder
   of progressively simpler variants until one resolves:

   | # | variant | example |
   |---|---------|---------|
   | 1 | raw address | `1071 Budapest 07. ker. Rottenbiller utca 49.` |
   | 2 | district marker stripped | `1071 Budapest Rottenbiller utca 49.` |
   | 3 | house-number range/suffix simplified | `Zsókavár utca 43-47 fszt` → `Zsókavár utca 43.` |
   | 4 | house number dropped, street kept | `1071 Budapest Rottenbiller utca` |

   This ladder is what lifts the hit rate on messy official-register
   addresses (2% → 94% on the Budapest list it was derived from).
2. **Geoapify** — only for addresses Nominatim couldn't resolve, so it
   burns very few of the free tier's **3,000 requests/day**.

`geocode_source` records which service resolved each row and
`geocode_query` which variant worked, so the outcome is always traceable.
An optional **country code** field (e.g. `hu`, `nl`) restricts Nominatim
to one country, which improves accuracy on single-country files.

**API key setup:** the Geoapify fallback needs a `GEOAPIFY_API_KEY`. Copy
`.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in
your key (that file is gitignored — it never gets committed), or paste one
into the tab's password field for the session. Without a key the tab still
runs Nominatim-only; unresolved rows just come back as `not_found`.

## Tests

```bash
pytest tests/ -v                                # everything
pytest tests/test_file_merger_logic.py -v        # one task
```
