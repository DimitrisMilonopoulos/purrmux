from collections.abc import Callable

from kitty.fast_data_types import Screen
from kitty.tab_bar import TabBarData

from . import config
from .colors import get_colors
from .modes import get_current_mode, get_mode_name
from .text import get_mode_text, get_static_text, get_tab_text


def draw_scaled(
    screen: Screen, text: str, scale: tuple[int, int] | None = None
) -> None:
    """Draw ``text`` at ``scale``, defaulting to ``config.TAB_BAR_TEXT_SCALE``.

    With a ``(n, d)`` fraction configured, glyphs are rendered at ``n/d`` of
    the normal size using kitty's text sizing protocol (OSC 66). The escape is
    pushed through the screen's parser because ``screen.draw`` writes literal
    characters; the cursor's current fg/bold carry over since sizing is
    orthogonal to SGR. Cell widths stay 1-per-char, so callers need no width
    accounting changes. Falls back to a plain draw when scaling is off, the
    text is empty, or it carries an escape that would corrupt the sequence.
    """
    if scale is None:
        scale = config.TAB_BAR_TEXT_SCALE
    if not text or scale is None or "\x1b" in text:
        screen.draw(text)
        return

    n, d = scale
    payload = f"\x1b]66;s=1:n={n}:d={d};{text}\x1b\\".encode("utf-8")
    buf = screen.test_create_write_buffer()
    screen.test_commit_write_buffer(payload, buf)
    screen.test_parse_written_data()


class Cell:
    def __init__(
        self,
        icon: str,
        text_fn: Callable[[int, TabBarData], str | None],
        tab: TabBarData | None = None,
        bg: int | None = None,
        fg: int | None = None,
        color: int | None = None,
        icon_fg: int | None = None,
        separator: str = "",
        border: tuple[str, str] = ("", ""),
        accent: bool = False,
        minimal_icon_fg: int | None = None,
    ) -> None:
        if bg is None or fg is None or color is None:
            colors = get_colors()
            bg = bg if bg is not None else colors.muted_body
            fg = fg if fg is not None else colors.muted_fg
            color = color if color is not None else colors.muted_chip
        if icon_fg is None:
            icon_fg = fg

        self.tab: TabBarData | None = tab
        self.fg: int = fg
        self.bg: int = bg
        self.color: int = color
        self.icon_fg: int = icon_fg
        self.icon: str = icon
        self.text_fn: Callable[[int, TabBarData], str | None] = text_fn
        self.border: tuple[str, str] = border
        self.separator: str = separator
        self.accent: bool = accent
        # Only the minimal style can colour the icon freely: in a chip it sits on
        # the icon block's background, where the contrast is already spoken for.
        self.minimal_icon_fg: int | None = minimal_icon_fg
        self.text_length_overhead: int = (
            len(self.border[0] + self.border[1] + self.separator + self.icon) + 1
        )
        # minimal: " <icon> <text> " -> lead + icon + mid + trail padding.
        # icons carry a trailing space for the chip layout; drop it so the
        # mid space isn't doubled.
        self.minimal_icon: str = self.icon.rstrip()
        self.minimal_overhead: int = len(self.minimal_icon) + 3

    def draw(self, screen: Screen, max_size: int, style: str | None = None) -> None:
        """Draw the cell in ``style``, defaulting to ``config.TAB_BAR_STYLE``.

        The style is a parameter so one part of the bar can differ from the
        rest: the sidebar draws its footer flat while the tabs stay chips.
        """
        if (style or config.TAB_BAR_STYLE) == "minimal":
            self._draw_minimal(screen, max_size)
        else:
            self._draw_chip(screen, max_size)

    def _draw_minimal(self, screen: Screen, max_size: int) -> None:
        text = self.text_fn(max_size - self.minimal_overhead, self.tab)

        if text is None:
            return

        screen.cursor.dim = False
        screen.cursor.italic = False
        screen.cursor.bg = 0

        screen.cursor.bold = False
        screen.cursor.fg = self.fg
        screen.draw(" ")

        if self.minimal_icon_fg is not None:
            screen.cursor.fg = self.minimal_icon_fg
        else:
            screen.cursor.fg = self.color if self.accent else self.fg
        screen.cursor.bold = True
        draw_scaled(screen, self.minimal_icon)
        screen.cursor.bold = False

        if text != "":
            screen.cursor.fg = self.fg
            screen.cursor.bold = self.accent
            screen.draw(" ")
            draw_scaled(screen, text)
            screen.cursor.bold = False

        screen.draw(" ")

    def _draw_chip(self, screen: Screen, max_size: int) -> None:
        text = self.text_fn(max_size - self.text_length_overhead, self.tab)

        if text is None:
            return

        screen.cursor.dim = False
        screen.cursor.bold = False
        screen.cursor.italic = False

        screen.cursor.bg = 0
        screen.cursor.fg = self.color
        screen.draw(self.border[0])

        screen.cursor.bg = self.color
        screen.cursor.fg = self.icon_fg
        screen.cursor.bold = True
        screen.draw(self.icon)
        screen.cursor.bold = False

        if text == "":
            screen.cursor.bg = 0
            screen.cursor.fg = self.color
            screen.draw(self.border[1])
        else:
            screen.cursor.bg = self.bg
            screen.cursor.fg = self.color
            screen.draw(self.separator)

            screen.cursor.fg = self.fg
            screen.draw(f" {text}")

            screen.cursor.fg = self.bg
            screen.cursor.bg = 0
            screen.draw(self.border[1])

    def length(self, max_size: int, style: str | None = None) -> int:
        if (style or config.TAB_BAR_STYLE) == "minimal":
            text = self.text_fn(max_size - self.minimal_overhead, self.tab)
            if text is None:
                return 0
            elif text == "":
                return len(self.minimal_icon) + 2
            else:
                return len(text) + self.minimal_overhead

        text = self.text_fn(max_size - self.text_length_overhead, self.tab)

        if text is None:
            return 0
        elif text == "":
            return len(self.icon + self.border[0] + self.border[1])
        else:
            return len(text) + self.text_length_overhead


def muted_cell(
    icon: str,
    text_fn: Callable[[int, TabBarData], str | None],
    tab: TabBarData,
    minimal_icon_fg: int | None = None,
) -> Cell:
    colors = get_colors()
    return Cell(
        icon,
        text_fn,
        tab,
        bg=colors.muted_body,
        fg=colors.muted_fg,
        color=colors.muted_chip,
        icon_fg=colors.muted_icon_fg,
        minimal_icon_fg=minimal_icon_fg,
    )


def accent_cell(
    icon: str,
    text_fn: Callable[[int, TabBarData], str | None],
    tab: TabBarData,
    minimal_icon_fg: int | None = None,
) -> Cell:
    colors = get_colors()
    return Cell(
        icon,
        text_fn,
        tab,
        bg=colors.accent_body,
        fg=colors.accent_fg,
        color=colors.accent_chip,
        icon_fg=colors.accent_icon_fg,
        accent=True,
        minimal_icon_fg=minimal_icon_fg,
    )


def get_tab_cell(
    tab: TabBarData,
    session_index: int,
    text_fn: Callable[[int, TabBarData], str | None] = get_tab_text,
) -> Cell:
    if tab.is_active:
        return accent_cell(str(session_index), text_fn, tab)
    return muted_cell(str(session_index), text_fn, tab)


def get_mode_cell(tab: TabBarData) -> Cell:
    mode_name = get_mode_name(tab)
    icon = config.ZOOM_ICON if mode_name == "zoom" else config.MODE_ICON
    if mode_name == "normal":
        return muted_cell(icon, get_mode_text, tab)
    return accent_cell(icon, get_mode_text, tab)


def _hint_cells(mode: str, tab: TabBarData) -> list[Cell]:
    """One cell per key, flattened out of the mode's groups.

    The horizontal bar lays hints out along a row, where the grouping the
    sidebar uses to save vertical space buys nothing.
    """
    return [
        muted_cell(f"{keys} ", get_static_text(label), tab)
        for keys, label in config.iter_hints(mode)
    ]


def get_mode_hint_cells(tab: TabBarData) -> list[Cell]:
    return _hint_cells(get_current_mode(), tab)


def get_leader_hint_cells(tab: TabBarData) -> list[Cell]:
    return _hint_cells("leader", tab)
