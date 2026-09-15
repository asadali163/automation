from tasks.base import Task

from .ui import render

TASK = Task(
    id="csv_merger",
    title="Merge CSVs",
    icon="",
    render=render,
    order=40,
)
