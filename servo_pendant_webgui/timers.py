"""
A ui.timer that does nothing once its page is gone.

NiceGUI 3 checks before each run whether the timer's client still exists, but then starts the callback as a new
task: when the browser tab is closed in between, the callback runs on a deleted client and NiceGUI warns "Client has
been deleted but is still being used" (https://github.com/zauberzeug/nicegui/issues/3028). The timer element is
deleted together with its client, so checking it right before the call closes that gap. An async callback must check
again after each await itself (e.g. `if element.is_deleted: return`).
"""

from nicegui import ui


def page_timer(interval, callback, **options):
    """ui.timer(interval, callback, **options), skipping the callback once the page's client has been deleted."""
    timer = None

    def run():
        if timer is None or timer.is_deleted:
            return None
        return callback()  # an async callback's coroutine is awaited by the timer

    timer = ui.timer(interval, run, **options)
    return timer
