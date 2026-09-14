"""Auto-discovers task modules so `app.py` never needs to change when a new
task is added.

Convention: every subpackage directly under `tasks/` that exposes a
module-level `TASK` (see `tasks.base.Task`) becomes one dashboard tab, in
alphabetical order by title.
"""
import importlib
import pkgutil
from typing import List

import tasks
from tasks.base import Task


def discover_tasks() -> List[Task]:
    found: List[Task] = []
    for module_info in pkgutil.iter_modules(tasks.__path__):
        if module_info.name.startswith("_") or module_info.name == "base":
            continue
        module = importlib.import_module(f"tasks.{module_info.name}")
        task = getattr(module, "TASK", None)
        if isinstance(task, Task):
            found.append(task)
    found.sort(key=lambda t: (t.order, t.title))
    return found
