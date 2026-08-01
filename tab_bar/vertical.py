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

So: one tab per row from the top, and the status the horizontal bar keeps in
its side sections (git branch, keyboard mode and its hints) stacked in the
spare space at the bottom.

Those rows are kitty's to place, not ours. It builds the click map from the
same ``start_row + i * tab_line_height`` it parks the cursor at, so drawing a
tab anywhere else would focus the wrong tab on a click — which is why there is
no room for a header row between groups of tabs.
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
    get_sidebar_list_text,
    get_sidebar_session_text,
    get_sidebar_tab_text,
    get_tab_icon,
    get_tab_subtitle,
    get_wd,
    resolve_agent_status,
)

CHIP = "chip"
HINT = "hint"
MODE = "mode"
SESSION = "session"
GAP = "gap"
# The rows a scaled-up row spills into. They draw nothing, and unlike a gap
# they are not spare: shedding one would let the row above it overdraw.
SPAN = "span"

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
    screen: Screen,
    row: int,
    cell: Cell,
    width: int,
    start: int,
    marker: str = "",
    cells: int = 1,
    scale: tuple[int, int] | None = None,
) -> None:
    screen.cursor.x = start
    screen.cursor.y = row
    reset_attrs(screen)

    if marker:
        screen.cursor.fg = get_colors().accent_chip
        screen.draw(marker)

    cell.draw(
        screen, max(1, width - len(marker)), config.VERTICAL_FOOTER_STYLE, cells, scale
    )


def draw_rule(screen: Screen, column: int, rows: range, bg: int = 0) -> None:
    """Draw the rule dividing the sidebar from the panes, over ``rows``.

    kitty has no option for a tab bar border, and it erases the tab bar screen
    before the first tab is drawn, so the whole column is painted from that
    first call.
    """
    for row in rows:
        screen.cursor.x = column
        screen.cursor.y = row
        reset_attrs(screen)
        screen.cursor.bg = bg
        screen.cursor.fg = get_colors().muted_chip
        screen.draw(config.VERTICAL_SEPARATOR)


def footer_cell(
    role: str,
    icon: str,
    text_fn: Callable[[int, TabBarData], str | None],
    tab: TabBarData,
) -> Cell:
    """A footer row: icon coloured by role, text muted.

    Attention keeps the accent treatment it has in the horizontal bar — bold,
    at full brightness — since it is the one row that means something is
    waiting. The session name takes it too: it is the anchor of the block, and
    weight is the only way to say so that costs no rows (see session_size).
    """
    icon_color = get_palette_color(config.VERTICAL_FOOTER_ICON_COLORS.get(role))
    factory = accent_cell if role in ("attention", "session") else muted_cell
    return factory(icon, text_fn, tab, minimal_icon_fg=icon_color)


def hint_rows_keys(mode: str) -> list[str]:
    """Grouped, keys only: ``modes  p t s o a l``.

    Two rows for the leader against ten for a row per key, which matters in a
    sidebar competing with the tabs for vertical space. Group names are padded
    to a common width so the keys line up in a column.
    """
    groups = config.MODE_HINTS.get(mode, [])
    if not groups:
        return []

    label_width = max(len(group) for group, _ in groups)
    return [
        f" {group.ljust(label_width)}  {' '.join(keys for keys, _ in items)}"
        for group, items in groups
    ]


def hint_rows_labels(mode: str, width: int) -> list[str]:
    """Every key with its own label, packed two to a row: ``p pane   t tab``.

    Falls back to one per row when the sidebar is too narrow to split.
    """
    pairs = [f"{keys} {label}" for keys, label in config.iter_hints(mode)]
    if not pairs:
        return []

    # Reading order runs across then down, so the columns interleave. The left
    # column is sized from what actually lands in it rather than by halving the
    # width, which would let a pair exactly filling its half run into its
    # neighbour with no gutter at all.
    left, right = pairs[0::2], pairs[1::2]
    column = max(len(pair) for pair in left)
    gutter = 2

    if right and 1 + column + gutter + max(len(pair) for pair in right) > width:
        return [f" {pair}" for pair in pairs]

    rows = []
    for index, entry in enumerate(left):
        mate = right[index] if index < len(right) else ""
        rows.append(f" {entry.ljust(column)}{' ' * gutter}{mate}".rstrip())
    return rows


def hint_rows(mode: str, width: int) -> list[str]:
    if config.MODE_HINT_STYLE == "labels":
        return hint_rows_labels(mode, width)
    return hint_rows_keys(mode)


def session_size() -> tuple[int, tuple[int, int] | None]:
    """Cells and fraction for the session row, from a plain size multiplier.

    The protocol only grows text a whole cell at a time, so a size like 3/2 is
    two cells with the glyph drawn at three quarters of them. Returns the cells
    to claim and the fraction to draw at, or no fraction at all when the row is
    the same size as everything else.
    """
    numerator, denominator = config.VERTICAL_SESSION_SCALE
    cells = max(1, -(-numerator // denominator))
    if cells == 1 and numerator == denominator:
        return 1, None
    return cells, (numerator, denominator * cells)


def footer_groups(tab: TabBarData, width: int) -> list[list[tuple[str, Any]]]:
    """The status rows to stack below the tabs, top-down, in groups.

    Two groups, split by what the rows answer. What is happening right now —
    the keyboard mode with its hints, and any agent waiting on you — then
    where you are: the branch and the session it belongs to. A blank row
    between them, none inside.
    """
    # Anything other than plain normal is worth a row: a keyboard mode, or the
    # zoom pseudo-mode, which get_mode_name derives from the layout while the
    # keyboard mode is still empty.
    mode = get_current_mode()
    keyboard: list[tuple[str, Any]] = []
    if mode or is_zoomed(tab):
        keyboard.append((MODE, get_mode_cell(tab)))
        keyboard.extend((HINT, text) for text in hint_rows(mode, width))
    elif config.LEADER_HINT:
        # Idle the row says how to reach everything else. It goes in as a plain
        # chip, without the marker that means the keyboard is busy.
        keyboard.append((CHIP, get_mode_cell(tab)))

    keyboard.append(
        (CHIP, footer_cell("attention", config.ATTENTION_ICON, get_agent_attention_text, tab))
    )

    # Narrowest first, so the session name lands at the bottom of the column as
    # the thing everything above it qualifies rather than as its heading.
    where: list[tuple[str, Any]] = [
        (CHIP, footer_cell("branch", config.BRANCH_ICON, get_session_branch, tab))
    ]
    if config.SHOW_RIGHT_FOLDER:
        where.append((CHIP, footer_cell("folder", config.FOLDER_ICON, get_wd, tab)))
    where.append(
        (SESSION, footer_cell("session", config.SESSION_ICON, get_sidebar_session_text, tab))
    )

    groups = [keyboard, where]

    # A cell whose text function has nothing to say (no repo, say) draws
    # nothing, so drop it instead of leaving a blank row — and drop the whole
    # group once nothing in it is left, so its gap goes too.
    kept = [
        [
            row
            for row in group
            if row[0] == HINT or row[1].length(width, config.VERTICAL_FOOTER_STYLE) > 0
        ]
        for group in groups
    ]
    return [group for group in kept if group]


def footer_rows(tab: TabBarData, width: int) -> list[tuple[str, Any]]:
    """The footer flattened, with blank rows between groups and at the bottom."""
    gap: list[tuple[str, Any]] = [(GAP, "")] * max(0, config.VERTICAL_FOOTER_SPACING)

    rows: list[tuple[str, Any]] = []
    for group in footer_groups(tab, width):
        if rows:
            rows.extend(gap)
        for kind, payload in group:
            rows.append((kind, payload))
            if kind == SESSION:
                rows.extend([(SPAN, "")] * (session_size()[0] - 1))

    if rows:
        rows.extend([(GAP, "")] * max(0, config.VERTICAL_FOOTER_BOTTOM_PAD))
    return rows


def trim_footer(rows: list[tuple[str, Any]], available: int) -> list[tuple[str, Any]]:
    """Fit the footer into ``available`` rows, shedding mode hints first.

    What is shed is said out loud: dropping the tail of the list silently is
    how the bar ends up claiming a mode has fewer keys than it does.
    """
    if available <= 0:
        return []

    # Blank rows are the first thing to go, bottom-most first: spacing is worth
    # having, but never at the price of a row that says something.
    while len(rows) > available:
        gaps = [i for i, (kind, _) in enumerate(rows) if kind == GAP]
        if not gaps:
            break
        del rows[gaps[-1]]

    dropped = 0
    while len(rows) > available:
        hints = [i for i, (kind, _) in enumerate(rows) if kind == HINT]
        if not hints:
            return rows[len(rows) - available :]
        del rows[hints[-1]]
        dropped += 1

    if dropped:
        hints = [i for i, (kind, _) in enumerate(rows) if kind == HINT]
        # The marker takes a row of its own, so it stands in for one more hint
        # than was cut. With no hint row left to give up there is nowhere to
        # put it, and the mode row alone has to carry the meaning.
        if hints:
            rows[hints[-1]] = (HINT, f" …+{dropped + 1} more")

    return rows


def draw_footer(
    screen: Screen, tab: TabBarData, width: int, first_free_row: int, start_column: int
) -> None:
    rows = trim_footer(footer_rows(tab, width), screen.lines - first_free_row)
    if not rows:
        return

    start = screen.lines - len(rows)
    for offset, (kind, payload) in enumerate(rows):
        if kind in (GAP, SPAN):
            # The tab bar screen is erased before the first tab is drawn, so a
            # blank row is a row nothing is drawn into.
            continue
        if kind == HINT:
            draw_dim(screen, start + offset, payload, width, start_column)
        else:
            # The mode is the one row worth a marker: it says the keyboard is
            # doing something other than typing.
            marker = config.VERTICAL_ACTIVE_MARKER if kind == MODE else ""
            cells, scale = session_size() if kind == SESSION else (1, None)
            draw_footer_cell(
                screen, start + offset, payload, width, start_column, marker,
                cells, scale,
            )


def draw_agent_status(
    screen: Screen, tab: TabBarData, row: int, width: int, start: int
) -> None:
    """Draw ``● working · claude`` under an agent's tab, for the chip style.

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


def tab_dot(tab: TabBarData) -> tuple[str, int]:
    """The glyph a list row leads with, and its colour.

    An agent's dot takes the colour of its status — the one thing in the
    sidebar worth catching your eye from across the screen. Everything else
    gets the app's icon where we know it, and a plain bullet where we don't.
    """
    resolved = resolve_agent_status(tab)
    if resolved is not None:
        status, _ = resolved
        dot = config.AGENT_STATUS_DOTS.get(status, config.AGENT_STATUS_DOT)
        return dot, get_status_color(status)

    colors = get_colors()
    icon = get_tab_icon(tab)
    if icon:
        return icon, colors.accent_chip if tab.is_active else colors.muted_chip
    return config.VERTICAL_TAB_BULLET, colors.muted_chip


def fill_row(screen: Screen, row: int, start: int, width: int, bg: int) -> None:
    """Paint ``width`` cells of background, so a row reads as one band."""
    screen.cursor.x = start
    screen.cursor.y = row
    reset_attrs(screen)
    screen.cursor.bg = bg
    screen.draw(" " * width)


def draw_list_tab(
    screen: Screen,
    tab: TabBarData,
    row: int,
    span: int,
    width: int,
    start: int,
    rows: int,
) -> None:
    """A tab as a flat row: dot, title, and a muted line under it.

    The active tab is a filled band across the whole column rather than a
    pill, which is what stops a stack of tabs reading as a stack of buttons
    next to a TUI. ``span`` is how far that band reaches and ``width`` how far
    the text may; they differ only when a rule needs a gutter. kitty fixes how
    many rows each tab gets, so the second line only exists when it handed out
    two.
    """
    colors = get_colors()
    band = colors.muted_body if tab.is_active else 0
    dot, dot_fg = tab_dot(tab)

    # The band is the whole of the active marker here, so no column is spent on
    # a gutter glyph. The second line sits under the title, not under the dot.
    gap = " " * config.VERTICAL_TAB_ICON_GAP
    indent = 1 + len(dot) + len(gap)
    budget = width - indent

    if tab.is_active:
        for offset in range(rows):
            fill_row(screen, row + offset, start, span, band)

    screen.cursor.x = start
    screen.cursor.y = row
    reset_attrs(screen)
    screen.cursor.bg = band
    screen.cursor.fg = dot_fg
    screen.cursor.bold = True
    screen.draw(f" {dot}")

    title = get_sidebar_list_text(budget, tab)
    if title:
        screen.cursor.fg = colors.accent_fg if tab.is_active else colors.muted_fg
        screen.cursor.bold = tab.is_active
        screen.draw(f"{gap}{title}")
        screen.cursor.bold = False

    if rows < 2:
        return

    subtitle = get_tab_subtitle(budget, tab)
    if not subtitle:
        return

    screen.cursor.x = start + indent
    screen.cursor.y = row + 1
    reset_attrs(screen)
    screen.cursor.bg = band
    screen.cursor.fg = colors.muted_fg
    screen.cursor.dim = True
    draw_scaled(screen, subtitle, config.VERTICAL_SECONDARY_TEXT_SCALE)
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

    # The band stops where the rule starts, one column short of the edge, so
    # the rule stays a divider between the sidebar and the panes rather than a
    # line drawn down the middle of a highlight. Text gets that same width with
    # no gutter of its own: the column is worth more as one more character of
    # title before it elides. kitty's budget (columns - 1) only caps it.
    rule = len(separator)
    span = max(1, screen.columns - rule)
    width = max(1, min(max_length, span))
    content_column = rule if separator and on_right else 0
    if separator and index == 1:
        draw_rule(screen, 0 if on_right else screen.columns - rule, range(screen.lines))

    # kitty gives each tab two rows whenever there are few enough of them.
    rows = row_pitch if row + row_pitch <= screen.lines else 1

    if config.VERTICAL_TAB_STYLE == "list":
        draw_list_tab(screen, tab, row, span, width, content_column, rows)
    else:
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

        # The spare row carries the agent status.
        if config.VERTICAL_SHOW_AGENT_STATUS and rows > 1:
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
