"""
Look of every webgui: palette, type, spacing and the Quasar overrides, for the light and the dark theme.

Shared webgui shell (from the nicegui-ros2-webgui skill): keep it identical across the webgui packages, so they all
look and behave the same. App specific styles go into the app's own CSS with the `--wg-*` tokens defined here.
"""

from pathlib import Path
from urllib.parse import quote

from nicegui import app, ui

FONT_DIR = Path(__file__).parent / "fonts"
FONT_URL = "/wg-fonts"

# Appearance, per browser: theme, text size and spacing. Each is a cookie, shared by all webguis of a host (cookies
# ignore the port), so what is chosen in one webgui is used by the others too the next time they are opened.
THEMES = {"light": "Light", "dark": "Dark", "auto": "System"}
TEXT_SIZES = {"small": "Small", "normal": "Normal", "large": "Large", "larger": "Larger"}
SPACINGS = {"compact": "Compact", "normal": "Normal", "roomy": "Roomy"}
TEXT_SCALE = {"small": 0.875, "normal": 1.0, "large": 1.133, "larger": 1.267}  # body text 13 / 15 / 17 / 19 px
SPACE_SCALE = {"compact": 0.75, "normal": 1.0, "roomy": 1.25}  # touch targets stay 44 px in every one

# name -> (cookie, choices, default); `?theme=dark&text=large&spacing=compact` in the URL wins (kiosks, screenshots)
APPEARANCE = {
    "theme": ("wg_theme", THEMES, "auto"),
    "text": ("wg_text", TEXT_SIZES, "normal"),
    "spacing": ("wg_spacing", SPACINGS, "normal"),
}

# Palette "Oxford steel", based on the coolors.co palette
# Rich black #0d1b2a / Oxford blue #1b263b / YInMn blue #415a77 / Shadow blue #778da9 / Platinum #e0e1dd.
# Status colours are tuned for >= 4.5:1 contrast on the surface colour (WCAG AA) in both themes.
LIGHT = {
    "bg": "#eef1f4",
    "surface": "#ffffff",
    "sunken": "#f5f7f9",
    "border": "#d5dbe2",
    "divider": "#e6eaef",
    "text": "#0d1b2a",
    "muted": "#4a6080",
    "subtle": "#7d8fa6",
    "primary": "#415a77",
    "primary-soft": "#e3e9f1",
    "on-primary": "#ffffff",
    "positive": "#2d7d5a",
    "positive-soft": "#e2f2ea",
    "warning": "#9a6210",
    "warning-soft": "#fbefdc",
    "negative": "#c0392b",
    "negative-soft": "#fbe5e2",
    "veil": "#0d1b2a59",
}
DARK = {
    "bg": "#0d1b2a",
    "surface": "#1b263b",
    "sunken": "#14202f",
    "border": "#2e3d56",
    "divider": "#243149",
    "text": "#e0e1dd",
    "muted": "#a3b1c6",
    "subtle": "#778da9",
    "primary": "#8fa6c4",
    "primary-soft": "#26354f",
    "on-primary": "#0d1b2a",
    "positive": "#5cc597",
    "positive-soft": "#163a30",
    "warning": "#e8b04b",
    "warning-soft": "#3a2e16",
    "negative": "#ef6b5e",
    "negative-soft": "#3d1f22",
    "veil": "#000000a0",
}


def _tokens(colors):
    tokens = "".join(f"--wg-{name}: {value}; " for name, value in colors.items())
    # Quasar's brand colours follow the theme. `!important`: NiceGUI sets them inline on <body>.
    quasar = {
        "primary": colors["primary"],
        "secondary": colors["muted"],
        "accent": colors["primary"],
        "positive": colors["positive"],
        "negative": colors["negative"],
        "warning": colors["warning"],
        "info": colors["primary"],
        "dark": DARK["surface"],
        "dark-page": DARK["bg"],
    }
    return tokens + "".join(f"--q-{name}: {value} !important; " for name, value in quasar.items())


_FONT_FACES = "".join(
    f'@font-face {{ font-family: "{family}"; font-weight: {weight}; font-style: normal; font-display: swap; '
    f'src: url({FONT_URL}/{file}.woff2) format("woff2"); }}\n'
    for family, weight, file in (
        ("IBM Plex Sans", 400, "ibm-plex-sans-latin-400-normal"),
        ("IBM Plex Sans", 500, "ibm-plex-sans-latin-500-normal"),
        ("IBM Plex Sans", 600, "ibm-plex-sans-latin-600-normal"),
        ("IBM Plex Mono", 400, "ibm-plex-mono-latin-400-normal"),
        ("IBM Plex Mono", 500, "ibm-plex-mono-latin-500-normal"),
    )
)

CSS = (
    _FONT_FACES
    + f"""
body {{ {_tokens(LIGHT)} }}
body.body--dark {{ {_tokens(DARK)} }}
:root {{ --wg-font: "IBM Plex Sans", system-ui, sans-serif; --wg-mono: "IBM Plex Mono", ui-monospace, monospace;
         --wg-header-h: 56px; --wg-footer-h: 36px; --wg-touch: 44px; --wg-radius: 10px; --wg-radius-sm: 8px;
         /* Appearance > Text size and Spacing set the two scales (per page, see appearance_css) */
         --wg-text-scale: 1; --wg-space-scale: 1;
         --wg-fs-xs: calc(12px * var(--wg-text-scale)); --wg-fs-sm: calc(13px * var(--wg-text-scale));
         --wg-fs-md: calc(14px * var(--wg-text-scale)); --wg-fs: calc(15px * var(--wg-text-scale));
         --wg-fs-lg: calc(17px * var(--wg-text-scale)); --wg-fs-xl: calc(21px * var(--wg-text-scale));
         --wg-fs-readout: calc(28px * var(--wg-text-scale));
         --wg-space-xs: calc(4px * var(--wg-space-scale)); --wg-space-sm: calc(8px * var(--wg-space-scale));
         --wg-space-in: calc(12px * var(--wg-space-scale)); --wg-space: calc(16px * var(--wg-space-scale));
         --wg-space-lg: calc(24px * var(--wg-space-scale)); --wg-space-xl: calc(32px * var(--wg-space-scale));
         --nicegui-default-padding: var(--wg-space); --nicegui-default-gap: var(--wg-space); }}
body {{ background: var(--wg-bg); color: var(--wg-text); font-family: var(--wg-font); font-size: var(--wg-fs);
        line-height: 1.45; -webkit-tap-highlight-color: transparent; }}
.q-field, .q-btn, .q-item, .q-tab, .q-toggle, .q-checkbox, .q-radio, .q-table, .q-notification, .q-tooltip,
.q-menu, .q-dialog {{ font-family: var(--wg-font); }}
.q-field, .q-menu, .q-item, .q-toggle, .q-checkbox, .q-radio {{ font-size: var(--wg-fs); }}

/* type scale (1.2 ratio from 15px, times the text size of Appearance) */
.wg-h1 {{ font-size: var(--wg-fs-xl); font-weight: 600; line-height: 1.25; }}
.wg-h2 {{ font-size: var(--wg-fs-lg); font-weight: 600; line-height: 1.3; }}
.wg-label {{ font-size: var(--wg-fs-sm); font-weight: 500; color: var(--wg-muted); }}
.wg-hint {{ font-size: var(--wg-fs-sm); color: var(--wg-muted); }}
.wg-mono {{ font-family: var(--wg-mono); font-size: var(--wg-fs-sm); }}
.wg-num {{ font-variant-numeric: tabular-nums; }}
.wg-readout {{ font-size: var(--wg-fs-readout); font-weight: 500; font-variant-numeric: tabular-nums;
               line-height: 1.1; }}

/* header */
.q-header.wg-header {{ background: var(--wg-surface); color: var(--wg-text); border-bottom: 1px solid var(--wg-border);
                       height: var(--wg-header-h); padding: 0 8px 0 16px; display: flex; align-items: center;
                       gap: 12px; flex-wrap: nowrap; }}
.wg-brand {{ display: flex; align-items: center; gap: 10px; min-width: 0; flex: 0 1 auto; }}
.wg-brand .q-icon {{ flex: none; }}
.wg-brand .q-icon {{ color: var(--wg-primary); }}
.wg-brand-name {{ font-size: var(--wg-fs-lg); font-weight: 600; white-space: nowrap; overflow: hidden;
                  text-overflow: ellipsis; }}
.wg-header-status {{ display: flex; align-items: center; gap: 8px; min-width: 0; overflow: hidden; }}
.wg-header-actions {{ display: flex; align-items: center; gap: 2px; margin-left: auto; flex: none; }}

/* footer: facts about the page and the node (no actions; those go into the header or the action bar) */
.q-footer.wg-footer {{ background: var(--wg-surface); color: var(--wg-muted); border-top: 1px solid var(--wg-border);
                       height: var(--wg-footer-h); padding: 0 16px; display: flex; align-items: center;
                       gap: 16px; flex-wrap: nowrap; font-size: var(--wg-fs-sm); white-space: nowrap; }}
.wg-footer-app, .wg-footer-shell {{ display: flex; align-items: center; gap: 12px; min-width: 0; }}
.wg-footer-app {{ flex: 1; overflow: hidden; }}
.wg-footer-shell {{ flex: none; margin-left: auto; }}
.wg-footer-app > *, .wg-footer-shell > * {{ display: inline-flex; align-items: center; gap: 6px; min-width: 0; }}
.wg-footer-app > * + *, .wg-footer-shell > * + * {{ padding-left: 12px; border-left: 1px solid var(--wg-divider); }}
.wg-footer .q-icon {{ font-size: 16px; color: var(--wg-subtle); }}

/* page content: the full width of the browser */
.nicegui-content.wg-root {{ padding: 0; gap: 0; }}
.wg-page {{ width: 100%; padding: var(--wg-space); display: flex;
            flex-direction: column; gap: var(--wg-space); }}
.wg-panel {{ background: var(--wg-surface); border: 1px solid var(--wg-border); border-radius: var(--wg-radius);
             padding: var(--wg-space); display: flex; flex-direction: column; gap: var(--wg-space-in); min-width: 0; }}
.wg-panel-head {{ display: flex; align-items: center; gap: 8px; min-height: 56px; margin: -8px 0 -4px; }}
.wg-panel-head .wg-h2 {{ flex: 1; min-width: 0; }}
.wg-sunken {{ background: var(--wg-sunken); border: 1px solid var(--wg-divider); border-radius: var(--wg-radius-sm); }}
.wg-actionbar {{ position: sticky; bottom: var(--wg-footer-h); z-index: 10; background: var(--wg-surface);
                 border-top: 1px solid var(--wg-border); padding: var(--wg-space-sm) var(--wg-space);
                 display: flex; align-items: center; gap: var(--wg-space-in); flex-wrap: wrap; }}
.wg-empty {{ display: flex; flex-direction: column; align-items: center; justify-content: center;
             gap: var(--wg-space-sm); padding: var(--wg-space-xl) var(--wg-space); text-align: center;
             color: var(--wg-muted); }}
.wg-empty .q-icon {{ color: var(--wg-subtle); }}

/* status: always icon + text, never colour alone */
.wg-status {{ display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 3px 10px 3px 8px;
              font-size: var(--wg-fs-sm); font-weight: 500; white-space: nowrap; background: var(--wg-sunken);
              color: var(--wg-muted); border: 1px solid var(--wg-divider); }}
.wg-status.wg-ok {{ background: var(--wg-positive-soft); color: var(--wg-positive); border-color: transparent; }}
.wg-status.wg-warn {{ background: var(--wg-warning-soft); color: var(--wg-warning); border-color: transparent; }}
.wg-status.wg-bad {{ background: var(--wg-negative-soft); color: var(--wg-negative); border-color: transparent; }}

/* touch: every control is at least 44 px tall / wide */
.q-btn {{ min-height: var(--wg-touch); border-radius: var(--wg-radius-sm); text-transform: none;
          font-weight: 500; letter-spacing: 0; font-size: var(--wg-fs); }}
.q-btn.q-btn--round {{ min-width: var(--wg-touch); border-radius: 50%; }}
.q-btn.wg-icon-btn {{ color: var(--wg-muted); }}
.q-btn.wg-big {{ min-height: 56px; font-size: var(--wg-fs-lg); padding: 0 28px; }}
.q-btn.wg-stop {{ min-height: 56px; font-size: var(--wg-fs-lg); font-weight: 600; padding: 0 28px; }}
.q-btn-group > .q-btn {{ border-radius: 0; }}
.q-btn-toggle {{ border: 1px solid var(--wg-border); border-radius: var(--wg-radius-sm); overflow: hidden; }}
.q-btn-toggle .q-btn:not(.bg-primary) {{ background: var(--wg-surface); color: var(--wg-text); }}
.q-item {{ min-height: var(--wg-touch); }}
.q-slider {{ min-height: var(--wg-touch); }}
.q-field--outlined .q-field__control {{ border-radius: var(--wg-radius-sm); }}
.q-field--outlined .q-field__control:before {{ border-color: var(--wg-border); }}
.q-tab {{ min-height: var(--wg-touch); text-transform: none; }}
.q-tab__label {{ font-size: var(--wg-fs); font-weight: 500; }}

/* tables */
.q-table__container {{ background: var(--wg-surface); color: var(--wg-text); border-radius: var(--wg-radius-sm);
                       box-shadow: none; border: 1px solid var(--wg-divider); }}
.q-table thead tr {{ background: var(--wg-sunken); }}
.q-table th {{ font-size: var(--wg-fs-sm); font-weight: 500; color: var(--wg-muted); }}
.q-table td {{ font-size: var(--wg-fs-md); font-variant-numeric: tabular-nums; }}
.q-table tbody td {{ height: var(--wg-touch); }}
.q-table--dark, .q-table--dark .q-table__bottom, .q-table--dark thead, .q-table--dark tr, .q-table--dark th,
.q-table--dark td {{ border-color: var(--wg-divider); }}

/* overlays */
.q-card {{ background: var(--wg-surface); color: var(--wg-text); border-radius: var(--wg-radius); }}
.q-dialog__backdrop {{ background: var(--wg-veil); }}
.q-tooltip {{ font-size: var(--wg-fs-sm); background: var(--wg-text); color: var(--wg-surface); }}
.q-notification {{ border-radius: var(--wg-radius-sm); font-size: var(--wg-fs); }}
kbd {{ font-family: var(--wg-mono); font-size: var(--wg-fs-sm); padding: 2px 7px; border-radius: 6px;
       white-space: nowrap; border: 1px solid var(--wg-border); border-bottom-width: 2px;
       background: var(--wg-sunken); }}

/* Text on filled status / primary colours: dark in the dark theme (the fills are light there). In a layer, as
   Quasar's text-white is !important in a later one (https://nicegui.io/documentation/section_styling_appearance) */
@layer components {{
  body.body--dark .bg-primary.text-white, body.body--dark .bg-positive.text-white,
  body.body--dark .bg-negative.text-white, body.body--dark .bg-warning.text-white,
  body.body--dark .q-notification.bg-positive, body.body--dark .q-notification.bg-negative,
  body.body--dark .q-notification.bg-warning, body.body--dark .q-notification.bg-info {{
    color: var(--wg-on-primary) !important; }}
  body.body--light .q-notification.bg-warning {{ color: #ffffff !important; }}
}}

/* keyboard focus is always visible */
:focus-visible {{ outline: 2px solid var(--wg-primary); outline-offset: 2px; }}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ transition-duration: 0s !important; animation-duration: 0s !important; }}
}}
/* phones and narrow tablets */
@media (max-width: 720px) {{
  .wg-header-status {{ display: none; }}
  .wg-page {{ padding: var(--wg-space-in); gap: var(--wg-space-in); }}
  .q-footer.wg-footer {{ padding: 0 12px; }}
  .wg-footer-version {{ display: none !important; }}
  .wg-panel {{ padding: var(--wg-space-in); }}
}}
"""
)


def install():
    """Once at start-up: fonts and the CSS for all pages."""
    app.add_static_files(FONT_URL, FONT_DIR)
    ui.add_css(CSS, shared=True)
    ui.add_head_html('<meta name="darkreader-lock">', shared=True)  # the dark theme is our own


def preferences(request):
    """Appearance of this browser, e.g. {"theme": "auto", "text": "normal", "spacing": "normal"}."""
    result = {}
    for name, (cookie, choices, default) in APPEARANCE.items():
        value = request.query_params.get(name) or request.cookies.get(cookie, default)
        result[name] = value if value in choices else default
    return result


def appearance_css(prefs):
    """Per page CSS for the text size and spacing, so the page is built with them (no jump)."""
    return (
        f"html:root {{ --wg-text-scale: {TEXT_SCALE[prefs['text']]}; "
        f"--wg-space-scale: {SPACE_SCALE[prefs['spacing']]}; }}"
    )


def apply_appearance(name, value):
    """Applies a text size or spacing to the open page at once."""
    variable, scales = {"text": ("--wg-text-scale", TEXT_SCALE), "spacing": ("--wg-space-scale", SPACE_SCALE)}[name]
    ui.run_javascript(f"document.documentElement.style.setProperty('{variable}', '{scales[value]}')")


def dark_value(preference):
    """The value of ui.dark_mode for a preference (None: follow the system)."""
    return {"light": False, "dark": True}.get(preference)


def save_preference(name, value):
    cookie = APPEARANCE[name][0]
    ui.run_javascript(f"document.cookie = '{cookie}={quote(value)}; path=/; max-age=31536000; SameSite=Lax'")


async def system_is_dark():
    return bool(await ui.run_javascript("window.matchMedia('(prefers-color-scheme: dark)').matches"))
