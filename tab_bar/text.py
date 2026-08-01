import os
import re
from collections.abc import Callable
from itertools import chain
from pathlib import Path

from kitty.tab_bar import TabAccessor, TabBarData

from . import config
from .attention import get_agent_status, tab_has_agent_attention
from .git import get_git_branch, shorten_branch
from .modes import get_current_mode, get_mode_name
from .session import get_session_root


def get_wd(max_size: int, tab: TabBarData) -> str | None:
    accessor = TabAccessor(tab.tab_id)

    wd = Path(accessor.active_wd or "")
    home = Path(os.getenv("HOME") or "")

    if wd.is_relative_to(home):
        wd = wd.relative_to(home)

        if wd == home:
            wd = Path("~")
        else:
            wd = Path("~") / wd

    parts = list(wd.parts)
    compressed = False
    if len(parts) > config.MAX_LENGTH_PATH:
        compressed = True
        parts = [parts[0], ".."] + parts[-config.MAX_LENGTH_PATH :]

    parts_cnt = 1 + compressed
    while parts_cnt != len(parts):
        wd = "/".join(parts[0 : 1 + compressed] + parts[parts_cnt:])
        if len(wd) <= max_size:
            return wd
        parts_cnt += 1

    if len(parts[-1]) <= max_size:
        return parts[-1]

    return None


def get_session_branch(max_size: int, tab: TabBarData) -> str | None:
    """The branch of the session's own directory, not of the focused window.

    A session is a project, and its branch belongs at the bottom of the sidebar
    once rather than under every tab. Reading it from the active window's cwd
    made it follow you around — cd into another repo and the footer reported
    that repo's branch for the session.
    """
    root = get_session_root(tab.session_name)

    if root is None:
        # No session file: the startup session, or one opened by hand. The
        # focused window's cwd is the only directory on offer.
        accessor = TabAccessor(tab.tab_id)
        if not accessor.active_wd:
            return None
        root = Path(accessor.active_wd)

    branch = get_git_branch(root)
    if branch is None:
        return None

    return shorten_branch(branch, max_size)


def resolve_agent_status(tab: TabBarData) -> tuple[str, str] | None:
    """``(status, agent)`` for an agent tab, or None when the tab isn't one.

    The status comes from the attention hooks via the agent_status user var.
    Without one — an agent whose hooks aren't installed, or one that hasn't
    reported yet this session — fall back to what kitty knows by itself: the
    attention flag, and whether the running process is an agent at all.
    """
    status, agent = get_agent_status(tab) or ("", "")

    if not agent:
        exe = TabAccessor(tab.tab_id).active_exe
        name = os.path.basename(str(exe)) if exe else ""
        agent = name if name in config.AGENT_EXES else ""

    if not status:
        if tab_has_agent_attention(tab):
            status = "waiting"
        elif agent:
            status = "running"

    if not status:
        return None

    return status, agent


def get_app_icon(accessor: TabAccessor) -> str | None:
    exe = accessor.active_exe
    if not exe:
        return None
    return config.APP_ICONS.get(os.path.basename(str(exe)))


def get_static_text(text: str) -> Callable[[int, TabBarData], str | None]:
    def inner(max_size: int, tab: TabBarData) -> str | None:
        if len(text) <= max_size:
            return text
        return ""

    return inner


def get_mode_text(max_size: int, tab: TabBarData) -> str | None:
    text = get_mode_name(tab)

    # Idle, the row is worth more as an advert for the leader than as the word
    # "normal". Callers still style off get_mode_name, so this only changes the
    # label, not whether the row reads as active.
    if text == "normal" and config.LEADER_HINT:
        text = config.LEADER_HINT

    if len(text) <= max_size:
        return text
    elif max_size >= 3:
        return text[:max_size]
    else:
        return None


def get_tab_name(tab: TabBarData) -> str:
    """What the tab is called, with nothing prepended to it."""
    if tab.title:
        return tab.title.removeprefix("#")
    return str(TabAccessor(tab.tab_id).active_exe)


def get_tab_icon(tab: TabBarData) -> str | None:
    if not config.ENABLE_APP_ICONS:
        return None
    return get_app_icon(TabAccessor(tab.tab_id))


def get_tab_title(tab: TabBarData) -> str:
    text = get_tab_name(tab)

    icon = get_tab_icon(tab)
    if icon:
        text = f"{icon} {text}"

    if tab_has_agent_attention(tab):
        text = f"! {text}"

    return text


def get_tab_text(max_size: int, tab: TabBarData) -> str | None:
    text = get_tab_title(tab)

    limit = config.MAX_LENGTH_TITLE_ACTIVE if tab.is_active else config.MAX_LENGTH_TITLE_INACTIVE
    if len(text) > limit:
        text = text[: limit - 1] + "…"

    if max_size <= len(text):
        return ""
    else:
        return text


def shorten_name(name: str, max_size: int) -> str | None:
    """Fit a dash/underscore separated name into ``max_size`` cells.

    Tries the name whole, then abbreviates leading segments to their initial
    (``api-gateway-service`` -> ``a-gateway-service`` -> ``a-g-service``), and
    only elides once that runs out — the progression get_wd and shorten_branch
    use for paths. Beats a hard cut wherever there is room to spare, since the
    tail is the part that identifies the project.
    """
    if max_size < 1:
        return None

    # Dots are left alone: in a name like example.com-website they read as
    # part of a word, not as a segment boundary.
    parts = re.split(r"([-_])", name)
    words, separators = parts[::2], parts[1::2]
    candidate = name

    for abbreviated in range(len(words)):
        kept = [word[:1] for word in words[:abbreviated]] + words[abbreviated:]
        candidate = "".join(chain.from_iterable(zip(kept, separators + [""])))
        if len(candidate) <= max_size:
            return candidate

    if max_size >= 2:
        return candidate[: max_size - 1] + "…"
    return candidate[:max_size]


def get_sidebar_session_text(max_size: int, tab: TabBarData) -> str | None:
    return shorten_name(tab.session_name or "none", max_size)


def get_sidebar_tab_text(max_size: int, tab: TabBarData) -> str | None:
    """Tab title for the vertical tab bar.

    The sidebar hands every tab the same width, so titles are fitted to it
    instead of to the horizontal bar's active/inactive budgets — and dropping
    the title (what get_tab_text does when the text does not fit) would leave a
    column of anonymous index chips.
    """
    text = get_tab_title(tab)

    if max_size < 1:
        return ""
    if len(text) > max_size:
        text = text[: max_size - 1] + "…"

    return text


def get_sidebar_list_text(max_size: int, tab: TabBarData) -> str | None:
    """Tab title for the sidebar's list style.

    The icon and the attention marker that get_tab_title prepends are left off:
    in a list the row already leads with a coloured dot carrying both.
    """
    text = get_tab_name(tab)

    if max_size < 1:
        return ""
    if len(text) > max_size:
        text = text[: max_size - 1] + "…"

    return text


def get_tab_subtitle(max_size: int, tab: TabBarData) -> str | None:
    """The muted line under a tab: what its agent is doing.

    A branch belongs to the session, not to a tab, so it is drawn once at the
    bottom of the sidebar instead of repeated under every tab of the same repo
    — where it was also wrong, being read from each tab's own cwd.
    """
    if max_size < 1:
        return None

    if config.VERTICAL_SHOW_AGENT_STATUS:
        resolved = resolve_agent_status(tab)
        if resolved is not None:
            status, agent = resolved
            label = f"{status} · {agent}" if agent else status
            if len(label) <= max_size:
                return label
            # Which agent matters less than what it is doing.
            if len(status) <= max_size:
                return status
            return f"{status[: max_size - 1]}…" if max_size >= 2 else None

    if config.VERTICAL_SHOW_TAB_BRANCH:
        return get_session_branch(max_size, tab)

    return None


def get_session_text(max_size: int, tab: TabBarData) -> str | None:
    text = tab.session_name
    if text == "":
        text = "none"
    if len(text) <= max_size:
        return text
    elif max_size >= 3:
        return text[:3]
    else:
        return None
