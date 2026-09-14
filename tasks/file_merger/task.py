from tasks.base import Task

from .ui import render

TASK = Task(
    id="file_merger",
    title="Merge Files",
    icon="",
    render=render,
    order=10,
)
