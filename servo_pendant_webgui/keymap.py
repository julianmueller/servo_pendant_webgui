"""
The pendant's keyboard shortcuts as a table: config/shortcuts.yaml maps each action to a key ("pause: space",
"base: b", "view: ctrl+alt+v"). Read whenever a page is built, so an edited file applies with the next page load.

load_keymap() returns {action: Key} for the actions that have a usable key, plus what was wrong with the others
(unknown action, a key that cannot be parsed, one used twice or reserved by the web GUI). Those actions simply get no
shortcut; the controls work as before.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

PACKAGE = "servo_pendant_webgui"
FILE = "shortcuts.yaml"

# Spoken names for keys whose KeyboardEvent.key is awkward to write in YAML
ALIASES = {"space": " ", "esc": "escape", "del": "delete", "up": "arrowup", "down": "arrowdown",
           "left": "arrowleft", "right": "arrowright", "plus": "+", "minus": "-"}  # fmt: skip
SPEC_RE = re.compile(r"((?:(?:ctrl|alt|shift)\+)*)(.+)")
NAME_RE = re.compile(r"[a-z][a-z0-9]*")  # enter, arrowup, f2, ...

# Keys that are taken elsewhere and cannot be given to an action: the shell's own shortcuts (shell/frame.py), Esc
# (stop) and the digits (held for joint jogging in components/key_jog.js, which takes them with any modifier)
SHELL_COMBOS = {"?": (False, False), ",": (True, False), "d": (False, False), "f": (False, False)}  # key: (ctrl, alt)
FIXED_KEYS = {"escape", *"123456789"}


@dataclass(frozen=True)
class Key:
    key: str  # KeyboardEvent.key, lower case (" " for space)
    ctrl: bool = False
    alt: bool = False
    shift: bool = False

    @property
    def options(self):
        """Keyword arguments for Shortcuts.add (shell/shortcuts.py)."""
        return {"ctrl": self.ctrl, "alt": self.alt, "shift": self.shift}

    @property
    def combo(self):
        """What makes two keys the same: Shift only counts with letters (as in shell/shortcuts.py)."""
        return self.key, self.ctrl, self.alt, self.shift and self.key.isalpha()


def config_path():
    """The installed config/shortcuts.yaml, else the one in the source tree (running from a checkout)."""
    try:
        from ament_index_python.packages import get_package_share_directory

        path = Path(get_package_share_directory(PACKAGE)) / "config" / FILE
        if path.is_file():
            return path.resolve()  # with --symlink-install: the file in the source tree, the one to edit
    except Exception:  # not installed with colcon (PackageNotFoundError), or no ament index
        pass
    return Path(__file__).resolve().parent.parent / "config" / FILE


def parse_key(spec):
    """'ctrl+s' -> Key('s', ctrl=True); '' or None -> None (no shortcut). Raises ValueError for a bad spec."""
    if spec is None:
        return None
    if isinstance(spec, bool) or not isinstance(spec, (str, int)):
        raise ValueError(f"{spec!r} is not a key (quote characters such as \"+\" and \"-\")")
    spec = str(spec).strip()
    if not spec:
        return None
    match = SPEC_RE.fullmatch(spec.lower())
    if match is None:
        raise ValueError(f"cannot read {spec!r}")
    modifiers, key = match.group(1).split("+")[:-1], match.group(2)
    key = ALIASES.get(key, key)
    if len(key) != 1 and not NAME_RE.fullmatch(key):
        raise ValueError(f"unknown key {match.group(2)!r} in {spec!r}")
    return Key(key, ctrl="ctrl" in modifiers, alt="alt" in modifiers, shift="shift" in modifiers)


def _reserved(k):
    if k.key in FIXED_KEYS:
        return "Esc and the digits are fixed (stop, joint jogging)"
    if SHELL_COMBOS.get(k.key) == (k.ctrl, k.alt):
        return "it is one of the web GUI's own shortcuts (?, Ctrl+, D, F)"
    return None


def load_keymap(actions, path=None):
    """Returns ({action: Key}, [problem, ...], path) for the given action names, from shortcuts.yaml."""
    path = Path(path) if path is not None else config_path()
    problems = []
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        return {}, [f"{path} could not be read, so there are no shortcuts besides the fixed ones: {e}"], path
    if not isinstance(data, dict):
        return {}, [f"{path} is not a table of <action>: <key> lines"], path
    keymap, used = {}, {}
    for action, spec in data.items():
        if action not in actions:
            problems.append(f"{action}: no such action (known: {', '.join(actions)})")
            continue
        try:
            key = parse_key(spec)
        except ValueError as e:
            problems.append(f"{action}: {e}")
            continue
        if key is None:
            continue  # switched off on purpose
        reason = _reserved(key)
        if reason is None and key.combo in used:
            reason = f"{used[key.combo]} has it already"
        if reason is not None:
            problems.append(f"{action}: {spec!r} is not available, {reason}")
            continue
        keymap[action], used[key.combo] = key, action
    missing = [a for a in actions if a not in data]
    if missing:
        problems.append(f"no line for {', '.join(missing)}: no shortcut (add one, or \"\" to say so)")
    return keymap, problems, path
