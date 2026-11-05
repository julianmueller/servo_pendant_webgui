"""Touch-friendly NiceGUI jog controls (spring-return slider and pad), keyboard jogging and 3D picking."""

from pathlib import Path

from nicegui import ui


def scene_pick_script():
    """The browser side of picking the jog gizmos in the 3D view (components/scene_pick.js), for add_body_html."""
    return f"<script>{(Path(__file__).parent / 'scene_pick.js').read_text()}</script>"


def _jog_args(e):
    return e.args[0] if isinstance(e.args, list) and e.args else e.args or {}


class _Disableable:
    def set_disabled(self, disabled):
        self._props['disabled'] = disabled
        self.update()


class JogSlider(_Disableable, ui.element, component='jog_slider.js'):
    """Spring-return velocity slider. Calls on_jog(value) with value in [-1, 1]; 0 on release."""

    def __init__(self, on_jog=None):
        super().__init__()
        self._props['external'] = 0.0
        if on_jog is not None:
            self.on('jog', lambda e: on_jog(float(_jog_args(e).get('value', 0.0))))

    def set_external(self, value):
        """Show a command from another source (keyboard) while the slider itself is not touched."""
        if self._props['external'] != value:
            self._props['external'] = value
            self.update()


class JogPad(_Disableable, ui.element, component='jog_pad.js'):
    """Spring-return touch pad / rocker, sized by CSS. Calls on_jog(x, y) with values in [-1, 1]; 0, 0 on release."""

    def __init__(self, axes='xy', labels=None, on_jog=None):
        super().__init__()
        self._props['axes'] = axes
        self._props['labels'] = labels or {}
        if on_jog is not None:
            self.on('jog', lambda e: on_jog(float(_jog_args(e).get('x', 0.0)), float(_jog_args(e).get('y', 0.0))))

    def set_labels(self, labels):
        self._props['labels'] = labels
        self.update()

    def set_highlight(self, side=None, sign=1):
        """Light up one half (left / right / up / down) of the pad in the colour of the sign; None: no highlight."""
        highlight = {'side': side, 'sign': 'pos' if sign > 0 else 'neg'} if side else {}
        if self._props.get('highlight') != highlight:
            self._props['highlight'] = highlight
            self.update()


class KeyJog(ui.element, component='key_jog.js'):
    """Keyboard jogging: keys 1..n jog joint 1..n (Ctrl/Shift: negative), Escape: on_stop()."""

    def __init__(self, count, on_jog, on_stop):
        super().__init__()
        self._props['count'] = count
        self.on('jog', lambda e: on_jog(int(_jog_args(e).get('index', 0)), float(_jog_args(e).get('value', 0.0))))
        self.on('stop', lambda _: on_stop())

    def set_count(self, count):
        self._props['count'] = count
        self.update()
