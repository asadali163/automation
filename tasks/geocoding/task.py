from tasks.base import Task

from .ui import render

TASK = Task(
    id="geocoding",
    title="Geocoding",
    icon="",
    render=render,
    order=50,
)
