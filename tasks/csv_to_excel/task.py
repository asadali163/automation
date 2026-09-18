from tasks.base import Task

from .ui import render

TASK = Task(
    id="csv_to_excel",
    title="CSV to Excel",
    icon="",
    render=render,
    order=60,  # 50 stays reserved for Geocoding, currently disabled
)
