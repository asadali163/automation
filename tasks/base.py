"""Shared contract every task module must implement.

A task is just a small metadata object pointing at a `render()` function.
`core.task_registry` scans the `tasks/` package for submodules that expose
a module-level `TASK` of this type and turns each one into a dashboard tab.
"""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Task:
    id: str                 # stable, unique, used as a Streamlit widget-key namespace
    title: str               # shown on the tab
    icon: str                 # emoji shown on the tab
    render: Callable[[], None]   # draws the task's whole UI when its tab is active
    order: int = 100          # tab position, ascending; ties break alphabetically by title
