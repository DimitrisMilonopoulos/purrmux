from enum import Enum

from kitty.fast_data_types import Screen, add_timer, get_boss
from kitty.tab_bar import DrawData, ExtraData, TabBarData

from . import config
from .attention import get_agent_attention_text, refresh_agent_attention
from .colors import get_colors
from .cells import (
    Cell,
    accent_cell,
    get_mode_cell,
    get_mode_hint_cells,
    get_sequence_hint_cells,
    get_tab_cell,
    muted_cell,
)
from .modes import get_current_mode
from .text import get_session_branch, get_session_text, get_wd
from .vertical import draw_vertical_tab


class CenterStrategy(Enum):
    EXPAND_ALL = 0
    EXPAND_ACTIVE = 1
    NO_EXPAND = 2
    SHOW_ACTIVE = 3
    SHOW_ACTIVE_NO_EXPAND = 4


timer_id = None

center: list[Cell] = []
active_index = 1
planned_tab_extents: list[tuple[int, int, int]] = []
session_tab_counts: dict[str, int] = {}


def draw_sep(screen: Screen):
    if config.TAB_BAR_STYLE != "minimal":
        screen.draw(" ")
        return

    screen.cursor.bold = False
    screen.cursor.italic = False
    screen.cursor.dim = False
    screen.cursor.bg = 0
    screen.cursor.fg = get_colors().muted_chip
    screen.draw(config.MINIMAL_SEPARATOR)


def redraw_tab_bar(_):
    tm = get_boss().active_tab_manager
    if tm is not None:
        tm.mark_tab_bar_dirty()


def get_session_tab_index(tab: TabBarData) -> int:
    session_key = tab.session_name or ""
    session_index = session_tab_counts.get(session_key, 0) + 1
    session_tab_counts[session_key] = session_index
    return session_index


def get_center_draw_plan(
    strategy: CenterStrategy, max_width: int
) -> list[tuple[int, int]]:
    match strategy:
        case CenterStrategy.EXPAND_ALL:
            return [(idx, max_width) for idx, _ in enumerate(center)]
        case CenterStrategy.EXPAND_ACTIVE:
            return [
                (idx, max_width if idx == active_index else 0)
                for idx, _ in enumerate(center)
            ]
        case CenterStrategy.NO_EXPAND:
            return [(idx, 0) for idx, _ in enumerate(center)]
        case CenterStrategy.SHOW_ACTIVE:
            return [(active_index, max_width)]
        case CenterStrategy.SHOW_ACTIVE_NO_EXPAND:
            return [(active_index, 0)]


def plan_tab_extents(columns: int) -> list[tuple[int, int, int]]:
    if not center:
        return []

    positions = [(0, 0, 0) for _ in center]
    mode = get_current_mode()

    if mode == "":
        strategy, length = center_strategy(columns)
        cursor = (columns - length) // 2
    elif mode == "tabmode":
        strategy, length = center_strategy(columns)
        cursor = columns - length
    else:
        return positions

    for idx, max_width in get_center_draw_plan(strategy, columns):
        cell_length = center[idx].length(max_width)
        end = cursor + cell_length
        positions[idx] = (cursor, end, end + 1)
        cursor = end + 1

    return positions


def center_strategy(max_width: int) -> tuple[CenterStrategy, int]:
    n_cells = len(center)

    length = n_cells - 1 + sum(map(lambda x: x.length(max_width), center))
    if length < max_width:
        return CenterStrategy.EXPAND_ALL, length

    length = n_cells - 1
    for index, cell in enumerate(center):
        if index == active_index:
            length += cell.length(max_width)
        else:
            length += cell.length(0)
    if length < max_width:
        return CenterStrategy.EXPAND_ACTIVE, length

    length = n_cells - 1 + sum(map(lambda x: x.length(0), center))
    if length < max_width:
        return CenterStrategy.NO_EXPAND, length

    length = center[active_index].length(max_width)
    if length < max_width:
        return CenterStrategy.SHOW_ACTIVE, length

    return CenterStrategy.SHOW_ACTIVE_NO_EXPAND, center[active_index].length(0)


def draw_center(screen: Screen, strategy: CenterStrategy, max_width: int):
    match strategy:
        case CenterStrategy.EXPAND_ALL:
            for idx, cell in enumerate(center):
                if idx != 0:
                    draw_sep(screen)
                cell.draw(screen, max_width)

        case CenterStrategy.EXPAND_ACTIVE:
            for idx, cell in enumerate(center):
                if idx != 0:
                    draw_sep(screen)
                cell.draw(screen, max_width * (idx == active_index))
        case CenterStrategy.NO_EXPAND:
            for idx, cell in enumerate(center):
                if idx != 0:
                    draw_sep(screen)
                cell.draw(screen, 0)
        case CenterStrategy.SHOW_ACTIVE:
            center[active_index].draw(screen, max_width)
        case CenterStrategy.SHOW_ACTIVE_NO_EXPAND:
            center[active_index].draw(screen, 0)


def draw_cells(screen: Screen, cells: list[Cell], max_length: int):
    remaining = max_length
    first = True

    for cell in cells:
        available = remaining - (0 if first else 1)
        if available <= 0:
            break

        cell_length = cell.length(available)
        if cell_length == 0 or cell_length > available:
            continue

        if not first:
            draw_sep(screen)
            remaining -= 1

        cell.draw(screen, available)
        remaining -= cell_length
        first = False


def draw_left(screen: Screen, max_length: int):
    tab = center[active_index].tab
    cells = [get_mode_cell(tab)]

    if get_current_mode() == "":
        cells.append(muted_cell(config.SESSION_ICON, get_session_text, tab))
        cells.append(accent_cell(config.ATTENTION_ICON, get_agent_attention_text, tab))
        if config.SHOW_SEQUENCE_HINTS:
            cells.extend(get_sequence_hint_cells(tab))
    else:
        cells.extend(get_mode_hint_cells(tab))

    draw_cells(screen, cells, max_length)


def get_right_cells() -> list[Cell]:
    tab = center[active_index].tab
    cells = [muted_cell(config.BRANCH_ICON, get_session_branch, tab)]
    if config.SHOW_RIGHT_FOLDER:
        cells.append(muted_cell(config.FOLDER_ICON, get_wd, tab))
    return cells


def get_right_layout(max_size: int) -> list[tuple[Cell, int]]:
    layout = []
    remaining = max_size
    first = True

    for cell in get_right_cells():
        available = remaining - (0 if first else 1)
        if available <= 0:
            break

        cell_length = cell.length(available)
        if cell_length == 0 or cell_length > available:
            continue

        layout.append((cell, cell_length))
        remaining -= cell_length + (0 if first else 1)
        first = False

    return layout


def get_right_length(screen: Screen) -> int:
    layout = get_right_layout(screen.columns)
    return sum(length for _, length in layout) + max(0, len(layout) - 1)


def draw_right(screen: Screen):
    max_size = screen.columns - screen.cursor.x
    layout = get_right_layout(max_size)
    total_length = sum(length for _, length in layout) + max(0, len(layout) - 1)

    offset_length = max_size - total_length
    screen.draw(" " * offset_length)

    first = True
    for cell, _ in layout:
        if not first:
            draw_sep(screen)

        cell.draw(screen, screen.columns - screen.cursor.x)
        first = False


def draw_tab(
    draw_data: DrawData,
    screen: Screen,
    tab: TabBarData,
    before: int,
    max_title_length: int,
    index: int,
    is_last: bool,
    extra_data: ExtraData,
) -> int:
    global center
    global timer_id
    global active_index
    global planned_tab_extents
    global session_tab_counts

    if timer_id is None:
        timer_id = add_timer(redraw_tab_bar, config.REFRESH_TIME, True)
    if index == 1:
        session_tab_counts = {}
        refresh_agent_attention()
    if tab.is_active:
        active_index = index - 1

    session_index = get_session_tab_index(tab)

    # Sidebar mode is a different beast: one tab per row, no layout pass, and
    # is_last set on every call. See vertical.py.
    if draw_data.tab_bar_edge in ("left", "right"):
        if index == 1:
            # Drop anything the horizontal path left behind, so toggling back
            # does not start from a stale plan.
            center = []
            planned_tab_extents = []
        return draw_vertical_tab(
            draw_data, screen, tab, index, session_index, max_title_length
        )

    tab_cell = get_tab_cell(tab, session_index)
    center.append(tab_cell)

    if extra_data.for_layout:
        if is_last:
            planned_tab_extents = plan_tab_extents(screen.columns)
            center = []
            session_tab_counts = {}
        screen.cursor.x = tab_cell.length(max_title_length)
        return screen.cursor.x

    planned_end = screen.cursor.x
    next_start = screen.cursor.x
    if index - 1 < len(planned_tab_extents):
        _, planned_end, next_start = planned_tab_extents[index - 1]

    if not is_last:
        screen.cursor.x = next_start
        return planned_end

    if is_last:
        screen.cursor.x = 0
        mode = get_current_mode()

        if mode == "":
            strategy, length = center_strategy(screen.columns)

            center_start_position = (screen.columns - length) // 2
            draw_left(screen, center_start_position - 1)

            screen.cursor.x = center_start_position
            draw_center(screen, strategy, screen.columns)
            screen.draw(" ")
            draw_right(screen)
        elif mode == "tabmode":
            strategy, length = center_strategy(screen.columns)
            center_start_position = screen.columns - length

            draw_left(screen, center_start_position - 1)

            screen.cursor.x = center_start_position
            draw_center(screen, strategy, screen.columns)
        else:
            max_left_length = screen.columns - get_right_length(screen) - 1
            draw_left(screen, max_left_length)
            draw_right(screen)

        center = []
        planned_tab_extents = []
        session_tab_counts = {}
        return screen.cursor.x
    return planned_end
