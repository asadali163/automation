from tasks.base import Task

from .ui import render

TASK = Task(
    id="deduplication",
    title="Deduplication",
    icon="",
    render=render,
    order=20,
)
