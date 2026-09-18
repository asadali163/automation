# Disabled for now — commented out so this tab doesn't show up on the
# dashboard. The task's code (task.py/ui.py/logic.py) is untouched; the
# registry only finds a task here if this module exposes a `TASK` object,
# so commenting out the export is enough to hide it without deleting
# anything. Uncomment these two lines to bring it back.
#
# from .task import TASK
#
# __all__ = ["TASK"]
