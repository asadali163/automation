from tasks.base import Task

from .ui import render

TASK = Task(
    id="geo_filter",
    title="Geo Boundary Filter",
    icon="📍",
    render=render,
    order=30,
)
