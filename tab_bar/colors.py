from dataclasses import dataclass

from kitty.fast_data_types import get_options
from kitty.tab_bar import as_rgb
from kitty.utils import color_as_int


@dataclass(frozen=True)
class Colors:
    accent_chip: int
    accent_body: int
    accent_fg: int
    accent_icon_fg: int
    muted_chip: int
    muted_body: int
    muted_fg: int
    muted_icon_fg: int


def _blend(c1: int, c2: int, t: float) -> int:
    r1, g1, b1 = (c1 >> 16) & 0xFF, (c1 >> 8) & 0xFF, c1 & 0xFF
    r2, g2, b2 = (c2 >> 16) & 0xFF, (c2 >> 8) & 0xFF, c2 & 0xFF
    r = int(r1 * (1 - t) + r2 * t)
    g = int(g1 * (1 - t) + g2 * t)
    b = int(b1 * (1 - t) + b2 * t)
    return (r << 16) | (g << 8) | b


def _luminance(c: int) -> float:
    r, g, b = (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _is_colorful(c: int, chroma_threshold: float = 0.20) -> bool:
    r, g, b = (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF
    return (max(r, g, b) - min(r, g, b)) / 255 >= chroma_threshold


def _distance(c1: int, c2: int) -> float:
    """How far apart two colours are, 0..1, as their widest channel gap."""
    return max(abs(((c1 >> s) & 0xFF) - ((c2 >> s) & 0xFF)) for s in (16, 8, 0)) / 255


# A tab bar background this close to the window background is the same surface
# as far as the eye is concerned, whatever the theme says.
_SAME_SURFACE = 0.04


def tab_bar_has_own_background() -> bool:
    """Whether the theme gives the tab bar a background of its own.

    kitty paints the bar in ``tab_bar_background`` when a theme sets one and in
    ``background`` otherwise. A theme that sets it far enough from the window
    background has already divided the sidebar from the panes, so nothing has
    to be drawn to do it. A shade or two apart doesn't count — plenty of themes
    set the option to the background they already have.
    """
    opts = get_options()
    if opts.tab_bar_background is None:
        return False
    bar = color_as_int(opts.tab_bar_background)
    return _distance(bar, color_as_int(opts.background)) >= _SAME_SURFACE


def _readable_fg(chip_bg: int, dark: int, light: int) -> int:
    chip_l = _luminance(chip_bg)
    return (
        dark
        if abs(chip_l - _luminance(dark)) > abs(chip_l - _luminance(light))
        else light
    )


_STATUS_PALETTE = {
    "working": "color3",
    "waiting": "color3",
    "running": "color3",
    "blocked": "color1",
    "error": "color1",
    "done": "color4",
}


def get_palette_color(name: str | None) -> int:
    """A colour from the theme's palette by option name, e.g. ``color4``.

    Falls back to the tab bar's muted colour, so callers can treat "no colour
    configured" and "unknown status" the same way.
    """
    if not name:
        return get_colors().muted_chip
    return as_rgb(color_as_int(getattr(get_options(), name)))


def get_status_color(status: str) -> int:
    """Colour for an agent status, from the theme's palette.

    Unknown and quiet statuses (idle) stay muted, so a dot only draws attention
    when the agent wants something.
    """
    return get_palette_color(_STATUS_PALETTE.get(status))


def get_colors() -> Colors:
    opts = get_options()
    bg: int = color_as_int(opts.background)
    fg: int = color_as_int(opts.foreground)
    cursor_int = color_as_int(opts.cursor)
    accent: int = cursor_int if _is_colorful(cursor_int) else color_as_int(opts.color4)
    accent_body = _blend(accent, bg, 0.65)
    muted_chip = _blend(bg, fg, 0.22)
    muted_body = _blend(bg, fg, 0.10)
    muted_fg = _blend(bg, fg, 0.70)
    return Colors(
        accent_chip=as_rgb(accent),
        accent_body=as_rgb(accent_body),
        accent_fg=as_rgb(_readable_fg(accent_body, bg, fg)),
        accent_icon_fg=as_rgb(_readable_fg(accent, bg, fg)),
        muted_chip=as_rgb(muted_chip),
        muted_body=as_rgb(muted_body),
        muted_fg=as_rgb(_readable_fg(muted_body, bg, muted_fg)),
        muted_icon_fg=as_rgb(_readable_fg(muted_chip, bg, muted_fg)),
    )
