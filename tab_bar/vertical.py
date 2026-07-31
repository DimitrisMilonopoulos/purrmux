"""Sidebar rendering for the custom tab bar (kitty >= 0.48 vertical tabs).

With ``tab_bar_edge left`` (or ``right``) kitty lays the tab bar out as a
sidebar and drives ``draw_tab`` very differently from the horizontal case:

* there is no layout pass (``extra_data.for_layout`` is never true) and
  ``is_last`` is true for *every* call, so the horizontal state machine in
  ``layout.py`` cannot be reused;
* before each call the cursor is parked at column 0 of that tab's first row,
  and each tab owns ``lines // n_tabs`` rows, capped at 2
  (``kitty.tab_bar.MAX_VERTICAL_TAB_LINES``);
* the whole tab bar screen is erased before the first call, so anything we
  draw outside our own row — the status footer here — survives.

So: one chip per row from the top, and the status the horizontal bar keeps in
its side sections (git branch, keyboard mode and its hints) stacked in the
spare space at the bottom.
"""

from collections.abc import Callable
from typing import Any

from kitty.fast_data_types import Screen
from kitty.tab_bar import DrawData, TabBarData

from . import config
from .attention import get_agent_attention_text
from .cells import (
    Cell,
    accent_cell,
    draw_scaled,
    get_mode_cell,
    get_tab_cell,
    muted_cell,
)
from .colors import get_colors, get_palette_color, get_status_color
from .modes import get_current_mode, is_zoomed
from .text import (
    get_session_branch,
    get_sidebar_session_text,
    get_sidebar_tab_text,
    get_wd,
    resolve_agent_status,
)

CHIP = "chip"
HINT = "hint"
MODE = "mode"

# Rows kitty gives each tab, and how many tabs it drew. Neither is passed to
# draw_tab, so both are measured from the cursor rows of consecutive tabs and
# reused on the next redraw; a tab count change settles one frame later.
row_pitch = 1
tab_count = 1
last_row: dict[int, int] = {}


def observe_row(index: int, row: int) -> None:
    global row_pitch, tab_count

    if index == 1:
        if last_row:
            tab_count = max(last_row)
        last_row.clear()
    elif index - 1 in last_row:
        row_pitch = max(1, row - last_row[index - 1])

    last_row[index] = row


def reset_attrs(screen: Screen) -> None:
    screen.cursor.bg = 0
    screen.cursor.bold = False
    screen.cursor.italic = False
    screen.cursor.dim = False


def draw_dim(screen: Screen, row: int, text: str, width: int, start: int = 0) -> None:
    if width <= 0 or not text:
        return

    screen.cursor.x = start
    screen.cursor.y = row
    reset_attrs(screen)
    screen.cursor.fg = get_colors().muted_fg
    screen.cursor.dim = True
    draw_scaled(screen, text[:width], config.VERTICAL_SECONDARY_TEXT_SCALE)
    screen.cursor.dim = False


def draw_footer_cell(
    screen: Screen, row: int, cell: Cell, width: int, start: int, marker: str = ""
) -> None:
    screen.cursor.x = start
    screen.cursor.y = row
    reset_attrs(screen)

    if marker:
        screen.cursor.fg = get_colors().accent_chip
        screen.draw(marker)

    cell.draw(screen, max(1, width - len(marker)), config.VERTICAL_FOOTER_STYLE)


def draw_separator(screen: Screen, column: int) -> None:
    """Draw the rule dividing the sidebar from the panes, full height.

    kitty has no option for a tab bar border, and it erases the tab bar screen
    before the first tab is drawn, so the whole column is painted from that
    first call.
    """
    for row in range(screen.lines):
        screen.cursor.x = column
        screen.cursor.y = row
        reset_attrs(screen)
        screen.cursor.fg = get_colors().muted_chip
        screen.draw(config.VERTICAL_SEPARATOR)


def footer_cell(
    role: str,
    icon: str,
    text_fn: Callable[[int, TabBarData], str | None],
    tab: TabBarData,
) -> Cell:
    """A footer row: icon coloured by role, text muted.

    Attention keeps the accent treatment it has in the horizontal bar — bold
    text — since it is the one row that means something is waiting.
    """
    icon_color = get_palette_color(config.VERTICAL_FOOTER_ICON_COLORS.get(role))
    factory = accent_cell if role == "attention" else muted_cell
    return factory(icon, text_fn, tab, minimal_icon_fg=icon_color)


def footer_rows(tab: TabBarData, width: int) -> list[tuple[str, Any]]:
    """The status rows to stack below the tabs, top-down."""
    rows: list[tuple[str, Any]] = []

    # Anything other than plain normal is worth a row: a keyboard mode, or the
    # zoom pseudo-mode, which get_mode_name derives from the layout while the
    # keyboard mode is still empty.
    mode = get_current_mode()
    if mode or is_zoomed(tab):
        rows.append((MODE, get_mode_cell(tab)))
        rows.extend(
            (HINT, f" {key}{label}") for key, label in config.MODE_HINTS.get(mode, [])
        )

    rows.append((CHIP, footer_cell("attention", config.ATTENTION_ICON, get_agent_attention_text, tab)))
    rows.append((CHIP, footer_cell("session", config.SESSION_ICON, get_sidebar_session_text, tab)))
    if config.SHOW_RIGHT_FOLDER:
        rows.append((CHIP, footer_cell("folder", config.FOLDER_ICON, get_wd, tab)))
    rows.append((CHIP, footer_cell("branch", config.BRANCH_ICON, get_session_branch, tab)))

    # A cell whose text function has nothing to say (no repo, say) draws
    # nothing, so drop it instead of leaving a blank row.
    return [
        row
        for row in rows
        if row[0] == HINT or row[1].length(width, config.VERTICAL_FOOTER_STYLE) > 0
    ]


def trim_footer(rows: list[tuple[str, Any]], available: int) -> list[tuple[str, Any]]:
    """Fit the footer into ``available`` rows, shedding mode hints first."""
    if available <= 0:
        return []

    while len(rows) > available:
        hints = [i for i, (kind, _) in enumerate(rows) if kind == HINT]
        if not hints:
            return rows[len(rows) - available :]
        del rows[hints[-1]]

    return rows


def draw_footer(
    screen: Screen, tab: TabBarData, width: int, first_free_row: int, start_column: int
) -> None:
    rows = trim_footer(footer_rows(tab, width), screen.lines - first_free_row)
    if not rows:
        return

    start = screen.lines - len(rows)
    for offset, (kind, payload) in enumerate(rows):
        if kind == HINT:
            draw_dim(screen, start + offset, payload, width, start_column)
        else:
            # The mode is the one row worth a marker: it says the keyboard is
            # doing something other than typing.
            marker = config.VERTICAL_ACTIVE_MARKER if kind == MODE else ""
            draw_footer_cell(
                screen, start + offset, payload, width, start_column, marker
            )


def draw_agent_status(
    screen: Screen, tab: TabBarData, row: int, width: int, start: int
) -> None:
    """Draw ``● working · claude`` under an agent's tab.

    Nothing is drawn for tabs that aren't running an agent, so the spare row
    kitty hands each tab stays empty for everything else.
    """
    resolved = resolve_agent_status(tab)
    if resolved is None:
        return

    status, agent = resolved
    dot = config.AGENT_STATUS_DOTS.get(status, config.AGENT_STATUS_DOT)
    available = width - len(dot) - 3  # indent, dot, space
    if available < 1:
        return

    label = f"{status} · {agent}" if agent else status
    if len(label) > available:
        # The status matters more than which agent it belongs to.
        label = status if len(status) <= available else f"{status[: available - 1]}…"

    screen.cursor.x = start
    screen.cursor.y = row
    reset_attrs(screen)
    screen.cursor.fg = get_status_color(status)
    screen.draw(f"  {dot}")

    screen.cursor.fg = get_colors().muted_fg
    screen.cursor.dim = True
    draw_scaled(screen, f" {label}", config.VERTICAL_SECONDARY_TEXT_SCALE)
    screen.cursor.dim = False


def draw_active_marker(screen: Screen, tab: TabBarData, marker: str) -> None:
    reset_attrs(screen)
    if tab.is_active:
        screen.cursor.fg = get_colors().accent_chip
        screen.draw(marker)
    else:
        screen.draw(" " * len(marker))


def draw_vertical_tab(
    draw_data: DrawData,
    screen: Screen,
    tab: TabBarData,
    index: int,
    session_index: int,
    max_length: int,
) -> int:
    row = screen.cursor.y
    observe_row(index, row)

    marker = config.VERTICAL_ACTIVE_MARKER
    separator = config.VERTICAL_SEPARATOR
    on_right = draw_data.tab_bar_edge == "right"

    # The rule lives on the inner edge — on the left it takes the column kitty
    # already keeps out of max_tab_length — plus a column of gutter so chips
    # don't butt up against it.
    reserved = len(separator) + 1 if separator else 0
    width = max(1, min(max_length, screen.columns - reserved))
    content_column = reserved if separator and on_right else 0
    if separator and index == 1:
        draw_separator(screen, 0 if on_right else screen.columns - len(separator))

    body_width = max(1, width - len(marker))
    screen.cursor.x = content_column
    screen.cursor.y = row

    if marker and not on_right:
        draw_active_marker(screen, tab, marker)

    cell = get_tab_cell(tab, session_index, get_sidebar_tab_text)
    chip_length = cell.length(body_width)
    reset_attrs(screen)
    cell.draw(screen, body_width)

    if marker and on_right:
        screen.draw(" " * max(0, width - len(marker) - chip_length))
        draw_active_marker(screen, tab, marker)

    # kitty gives each tab two rows whenever there are few enough of them; the
    # second one carries the agent status.
    if config.VERTICAL_SHOW_AGENT_STATUS and row_pitch > 1 and row + 1 < screen.lines:
        draw_agent_status(screen, tab, row + 1, width, content_column)

    # The footer belongs to the active tab, so draw it from that tab's call —
    # but only into rows no tab can claim, since later tabs draw over it.
    if config.VERTICAL_SHOW_STATUS and tab.is_active:
        first_tab_row = last_row.get(1, row)
        draw_footer(
            screen, tab, width, first_tab_row + tab_count * row_pitch, content_column
        )

    screen.cursor.x = 0
    screen.cursor.y = row
    return screen.cursor.x
