from collections.abc import Generator
from typing import TYPE_CHECKING

from kitty.fast_data_types import get_boss

from . import config

if TYPE_CHECKING:
    from kitty.tab_bar import TabBarData

agent_attention_tab_ids: set[int] = set()
agent_attention_sessions: list[str] = []
# tab id -> (status, agent name), from the agent_status/agent_name user vars the
# attention hooks set. Unlike attention, a status is collected for the focused
# window too: "working" is exactly what the agent you are watching is doing.
agent_status_by_tab: dict[int, tuple[str, str]] = {}


def _iter_live_tabs() -> Generator:
    boss = get_boss()
    all_tabs = getattr(boss, "all_tabs", None)
    if callable(all_tabs):
        yield from all_tabs
        return
    if all_tabs is not None:
        yield from all_tabs
        return

    tab_managers = getattr(boss, "os_window_map", {}) or {}
    for tab_manager in tab_managers.values():
        tabs = getattr(tab_manager, "tabs", None)
        if tabs is not None:
            yield from tabs
            continue
        try:
            yield from tab_manager
        except TypeError:
            continue


def _iter_live_windows(tab) -> Generator:
    try:
        yield from tab
        return
    except TypeError:
        pass

    windows = getattr(tab, "windows", None)
    if windows is None:
        return

    for attr in ("all_windows", "windows"):
        values = getattr(windows, attr, None)
        if callable(values):
            values = values()
        if values is not None:
            yield from values
            return

    try:
        yield from windows
    except TypeError:
        return


def _live_tab_id(tab) -> int | None:
    tab_id = getattr(tab, "id", None)
    if tab_id is None:
        tab_id = getattr(tab, "tab_id", None)
    return tab_id if isinstance(tab_id, int) else None


def _live_tab_session(tab, user_vars: dict[str, str]) -> str:
    session_name = user_vars.get("kitty_zoxide_session")
    if session_name:
        return session_name

    session_name = getattr(tab, "session_name", "")
    if isinstance(session_name, str) and session_name:
        return session_name

    title = getattr(tab, "title", "")
    return title if isinstance(title, str) else ""


def refresh_agent_attention() -> None:
    global agent_attention_tab_ids
    global agent_attention_sessions
    global agent_status_by_tab

    if not config.SHOW_AGENT_ATTENTION:
        agent_attention_tab_ids = set()
        agent_attention_sessions = []
        agent_status_by_tab = {}
        return

    try:
        active_window_id = getattr(get_boss().active_window, "id", None)
    except Exception:
        active_window_id = None

    tab_ids: set[int] = set()
    sessions: set[str] = set()
    statuses: dict[int, tuple[str, str]] = {}

    try:
        tabs = list(_iter_live_tabs())
    except Exception:
        agent_attention_tab_ids = set()
        agent_attention_sessions = []
        agent_status_by_tab = {}
        return

    for live_tab in tabs:
        tab_id = _live_tab_id(live_tab)
        if tab_id is None:
            continue

        for window in _iter_live_windows(live_tab):
            user_vars = getattr(window, "user_vars", {}) or {}
            if not isinstance(user_vars, dict):
                continue

            status = user_vars.get("agent_status") or ""
            agent_name = user_vars.get("agent_name") or ""
            if (status or agent_name) and tab_id not in statuses:
                statuses[tab_id] = (status, agent_name)

            if getattr(window, "id", None) == active_window_id:
                continue
            if user_vars.get("agent_attention") != "1":
                continue

            tab_ids.add(tab_id)
            session_name = _live_tab_session(live_tab, user_vars)
            if session_name:
                sessions.add(session_name)

    agent_attention_tab_ids = tab_ids
    agent_attention_sessions = sorted(sessions)
    agent_status_by_tab = statuses


def get_agent_attention() -> tuple[set[int], list[str]]:
    return agent_attention_tab_ids, agent_attention_sessions


def get_agent_status(tab: "TabBarData") -> tuple[str, str] | None:
    return agent_status_by_tab.get(tab.tab_id)


def tab_has_agent_attention(tab: "TabBarData") -> bool:
    tab_ids, _ = get_agent_attention()
    return tab.tab_id in tab_ids


def get_agent_attention_text(max_size: int, tab: "TabBarData") -> str | None:
    tab_ids, sessions = get_agent_attention()
    if not tab_ids:
        return None

    if sessions:
        text = " ".join(sessions[:2])
        if len(sessions) > 2:
            text = f"{text} +{len(sessions) - 2}"
        if len(text) <= max_size:
            return text

    count = str(len(tab_ids))
    return count if len(count) <= max_size else ""
