"""
Keyboard shortcuts of a page, with a help dialog that lists them (press ?).

Shared webgui shell (from the nicegui-ros2-webgui skill): keep it identical across the webgui packages.
"""

import inspect
import json
from dataclasses import dataclass

from nicegui import ui

# Shown with these names in the help and in tooltips
KEY_NAMES = {
    " ": "Space",
    "escape": "Esc",
    "arrowup": "↑",
    "arrowdown": "↓",
    "arrowleft": "←",
    "arrowright": "→",
    "enter": "Enter",
    "delete": "Del",
    "backspace": "Backspace",
}


@dataclass
class Shortcut:
    key: str  # KeyboardEvent.key, lower case: "d", "?", ",", "escape", "arrowup", " "
    description: str
    handler: object
    ctrl: bool = False  # Ctrl, or Cmd on a Mac
    shift: bool = False
    alt: bool = False
    group: str = "General"
    repeat: bool = False  # also on key repeat (holding the key)

    @property
    def combo(self):
        """Same id as COMBO_JS computes in the browser."""
        shift = "s" if self.shift and self.key.isalpha() else ""
        return f"{'c' if self.ctrl else ''}{'a' if self.alt else ''}{shift}:{self.key}"

    @property
    def label(self):
        parts = (["Ctrl"] if self.ctrl else []) + (["Alt"] if self.alt else []) + (["Shift"] if self.shift else [])
        return "+".join(parts + [KEY_NAMES.get(self.key, self.key.upper())])

    def matches(self, e):
        m = e.modifiers
        if str(e.key.name).lower() != self.key or (m.ctrl or m.meta) != self.ctrl or m.alt != self.alt:
            return False
        # Shift is part of punctuation keys ("?" is Shift+/ on most layouts): only compared for letters and names
        return m.shift == self.shift if self.key.isalpha() else True


# Code editors (CodeMirror, ui.codemirror) type into a contenteditable element, not an input: ui.keyboard's
# `ignore` (tag names) does not see them, so keys typed there are filtered here. Ctrl / Cmd combinations still
# count (e.g. Ctrl+Enter to send what was typed): plain keys are typing. `e`: the key event's arguments.
EDITING_JS = "(document.activeElement && document.activeElement.isContentEditable && !(e.ctrlKey || e.metaKey))"

# Keeps the browser from also acting on our keys (Firefox: "/" opens quick find, Space scrolls, Ctrl+, ...).
# Esc is left alone: dialogs close with it.
COMBO_JS = """(e) => {
  if (e.action !== "keydown" || !window.wgShortcutCombos || """ + EDITING_JS + """) return;
  const key = e.key.toLowerCase();
  const id = (e.ctrlKey || e.metaKey ? "c" : "") + (e.altKey ? "a" : "") + (/^[a-z]$/.test(key) && e.shiftKey ? "s" : "");
  if (key !== "escape" && window.wgShortcutCombos.has(id + ":" + key)) e.event.preventDefault();
}"""


class _Keyboard(ui.keyboard):
    """ui.keyboard that also ignores keys typed into editable elements (EDITING_JS)."""

    def on(self, type, handler=None, args=None, *, js_handler="(...args) => emit(...args)", **kwargs):  # noqa: A002
        if type == "key" and js_handler == "(...args) => emit(...args)":
            js_handler = f"(...args) => {{ const e = args[0] || {{}}; if ({EDITING_JS}) return; emit(...args); }}"
        return super().on(type, handler, args, js_handler=js_handler, **kwargs)


class Shortcuts:
    """
    One per page. Keys typed into inputs and editors are ignored, so plain letters are fine as shortcuts.
    add() returns the label (e.g. "Ctrl+S") to put into the tooltip of the matching button.
    """

    def __init__(self):
        self._items = []
        # not ignored on buttons: a clicked button keeps the focus and would block every shortcut
        self.keyboard = _Keyboard(on_key=self._on_key, ignore=["input", "select", "textarea"])
        self.keyboard.on("key", js_handler=COMBO_JS)
        self._synced = False
        ui.timer(0, self._sync, once=True)  # once the page is connected and every shortcut is added
        with ui.dialog() as self.dialog, ui.card().classes("wg-shortcuts"):
            self._list = ui.column().classes("w-full gap-0")

    def add(self, key, description, handler, **options):
        shortcut = Shortcut(key.lower(), description, handler, **options)
        self._items = [s for s in self._items if s.combo != shortcut.combo] + [shortcut]
        if self._synced:
            self._sync()
        return shortcut.label

    def _sync(self):
        self._synced = True
        ui.run_javascript(f"window.wgShortcutCombos = new Set({json.dumps([s.combo for s in self._items])})")

    async def _on_key(self, e):
        if not e.action.keydown:
            return
        for s in self._items:
            if s.matches(e):
                if e.action.repeat and not s.repeat:
                    return
                result = s.handler()
                if inspect.isawaitable(result):
                    await result
                return

    def show_help(self):
        self._list.clear()
        with self._list:
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label("Keyboard shortcuts").classes("wg-h2 flex-1")
                ui.button(icon="sym_o_close", on_click=self.dialog.close).props("flat round").classes("wg-icon-btn")
            groups = {}
            for s in self._items:
                groups.setdefault(s.group, []).append(s)
            for group, items in groups.items():
                ui.label(group).classes("wg-label pt-4 pb-1")
                for s in items:
                    with ui.row().classes("w-full items-center no-wrap gap-4 py-1"):
                        ui.label(s.description).classes("flex-1")
                        ui.html(f"<kbd>{s.label}</kbd>", sanitize=False)
        self.dialog.open()
