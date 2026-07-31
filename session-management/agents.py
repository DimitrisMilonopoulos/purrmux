#!/usr/bin/env python3
"""Agent state shared by the attention picker and the agent overview.

Agents report into kitty user vars from the hooks in ``hooks/``: ``agent_status``
(working/blocked/done/idle/error), ``agent_name``, ``agent_status_at``, and the
``agent_attention*`` trio. Everything else — session, title, cwd — comes straight
off ``kitten @ ls``, and the branch is read from the repo's HEAD file.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

FD_RE = re.compile(r"fd:(\d+)")

# Statuses coloured to match the tab bar's dots. The order decides where an
# agent lands once the ones actually waiting for you are out of the way.
STATUS_COLORS = {
    "blocked": "1;31",
    "error": "1;31",
    "waiting": "1;33",
    "working": "1;33",
    "done": "1;34",
}
STATUS_ORDER = ("blocked", "error", "waiting", "done", "working", "running", "idle")
STATUS_DOTS = {"idle": "○"}
STATUS_DOT = "●"

_branch_cache: dict[str, str] = {}


def kitten_pass_fds() -> tuple[int, ...]:
    """The control socket kitty may hand us as an inherited descriptor.

    subprocess closes descriptors above stderr by default, which would leave
    ``kitten @ --to fd:N`` talking to nothing.
    """
    match = FD_RE.search(os.environ.get("KITTY_LISTEN_ON", ""))
    if match is None:
        return ()
    return (int(match.group(1)),)


def child_listen_on() -> str:
    """An address grandchild processes can reach kitty on.

    ``launch --allow-remote-control`` hands the control socket to this process as
    an inherited descriptor, which processes further down (fzf's preview command,
    say) cannot open. The instance-wide socket from os-${KITTY_OS}.conf can be
    rebuilt from the pid, and works for anyone.
    """
    listen_on = os.environ.get("KITTY_LISTEN_ON", "")
    if listen_on and not listen_on.startswith("fd:"):
        return listen_on

    pid = os.environ.get("KITTY_PID")
    if not pid:
        return listen_on
    if sys.platform == "darwin":
        return f"unix:/tmp/mykitty-{pid}"
    return f"unix:@kitty-{pid}"


def run_kitten(*args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["kitten", "@", *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            pass_fds=kitten_pass_fds(),
        )
    except FileNotFoundError:
        print("agents: kitten command not found", file=sys.stderr)
        return None


def kitty_state() -> object | None:
    result = run_kitten("ls")
    if result is None:
        return None
    if result.returncode != 0:
        print(result.stderr.strip() or "agents: failed to query kitty", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"agents: failed to parse kitty state ({exc})", file=sys.stderr)
        return None


def color(text: str, code: str, *, ansi: bool) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if ansi else text


def clean_text(value: object) -> str:
    return str(value or "").replace("\t", " ").replace("\n", " ").strip()


def git_branch(cwd: str) -> str:
    """Branch name for ``cwd``, read from HEAD without shelling out to git."""
    if not cwd:
        return ""
    if cwd in _branch_cache:
        return _branch_cache[cwd]

    branch = ""
    path = Path(cwd)
    for candidate in [path, *path.parents]:
        dotgit = candidate / ".git"
        git_dir: Path | None = None

        if dotgit.is_dir():
            git_dir = dotgit
        elif dotgit.is_file():
            try:
                spec = dotgit.read_text(encoding="utf-8").strip()
            except OSError:
                break
            prefix, _, value = spec.partition(":")
            if prefix == "gitdir" and value.strip():
                git_dir = Path(value.strip())
                if not git_dir.is_absolute():
                    git_dir = candidate / git_dir
        if git_dir is None:
            continue

        try:
            head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        except OSError:
            break
        ref = "ref: refs/heads/"
        branch = head.removeprefix(ref) if head.startswith(ref) else head[:7]
        break

    _branch_cache[cwd] = branch
    return branch


def elapsed(timestamp: str) -> str:
    """Compact age of a unix timestamp: 42s, 14m, 3h, 2d."""
    try:
        then = int(timestamp)
    except (TypeError, ValueError):
        return ""
    if then <= 0:
        return ""

    seconds = max(0, int(time.time()) - then)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


@dataclass(frozen=True)
class Agent:
    window_id: int
    session: str
    agent: str
    status: str
    has_attention: bool
    title: str
    cwd: str
    status_at: str
    is_focused: bool

    @property
    def branch(self) -> str:
        return git_branch(self.cwd)

    @property
    def age(self) -> str:
        return elapsed(self.status_at)

    @property
    def dot(self) -> str:
        return STATUS_DOTS.get(self.status, STATUS_DOT)

    @property
    def status_color(self) -> str:
        return STATUS_COLORS.get(self.status, "2;37")

    @property
    def sort_key(self) -> tuple[int, int, str]:
        rank = (
            STATUS_ORDER.index(self.status)
            if self.status in STATUS_ORDER
            else len(STATUS_ORDER)
        )
        return (0 if self.has_attention else 1, rank, self.title)


def collect_agents(data: object, *, attention_only: bool = False) -> list[Agent]:
    """Every agent window kitty knows about, the ones wanting you first.

    An agent is a window that reported a status or a name through the attention
    hooks; pass attention_only to keep it to windows actually waiting for you.
    """
    agents: list[Agent] = []
    if not isinstance(data, list):
        return agents

    for os_window in data:
        if not isinstance(os_window, dict):
            continue
        os_focused = bool(os_window.get("is_focused"))
        tabs = os_window.get("tabs")
        if not isinstance(tabs, list):
            continue

        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            tab_focused = bool(tab.get("is_focused"))
            tab_title = clean_text(tab.get("title")) or f"tab {tab.get('id', '?')}"
            windows = tab.get("windows")
            if not isinstance(windows, list):
                continue

            for window in windows:
                if not isinstance(window, dict):
                    continue
                user_vars = window.get("user_vars")
                if not isinstance(user_vars, dict):
                    continue

                status = clean_text(user_vars.get("agent_status"))
                agent = clean_text(user_vars.get("agent_name"))
                is_focused = (
                    os_focused and tab_focused and bool(window.get("is_focused"))
                )
                # Attention is never claimed by the window you are looking at.
                has_attention = (
                    user_vars.get("agent_attention") == "1" and not is_focused
                )

                if not has_attention and (attention_only or not (status or agent)):
                    continue

                window_id = window.get("id")
                if not isinstance(window_id, int):
                    continue

                if not status:
                    status = "waiting" if has_attention else "running"

                session = clean_text(
                    user_vars.get("kitty_zoxide_session")
                    or window.get("session_name")
                    or tab.get("session_name")
                )
                agents.append(
                    Agent(
                        window_id=window_id,
                        session=session,
                        agent=agent or "agent",
                        status=status,
                        has_attention=has_attention,
                        title=tab_title,
                        cwd=clean_text(window.get("cwd")),
                        status_at=clean_text(
                            user_vars.get("agent_status_at")
                            or user_vars.get("agent_attention_at")
                        ),
                        is_focused=is_focused,
                    )
                )

    agents.sort(key=lambda agent: agent.sort_key)
    return agents


def group_by_session(agents: list[Agent]) -> list[tuple[str, list[Agent]]]:
    """Agents bucketed per session, the session wanting you most first."""
    groups: dict[str, list[Agent]] = {}
    for agent in agents:
        groups.setdefault(agent.session, []).append(agent)

    return sorted(
        groups.items(),
        key=lambda item: (min(agent.sort_key for agent in item[1]), item[0]),
    )


def status_counts(agents: list[Agent]) -> str:
    """"1 blocked · 2 working" for a header line."""
    counts: dict[str, int] = {}
    for agent in agents:
        counts[agent.status] = counts.get(agent.status, 0) + 1
    order = [status for status in STATUS_ORDER if status in counts]
    order += sorted(status for status in counts if status not in STATUS_ORDER)
    return " · ".join(f"{counts[status]} {status}" for status in order)


def clear_attention(window_id: int) -> int:
    """Drop a window's attention, keeping what the agent is and is doing."""
    result = run_kitten(
        "set-user-vars",
        "--match",
        f"id:{window_id}",
        "agent_attention",
        "agent_attention_source",
        "agent_attention_at",
    )
    if result is None:
        return 1
    return result.returncode
