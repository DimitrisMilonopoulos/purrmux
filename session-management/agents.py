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
import socket
import subprocess
import sys
import threading
import time
from contextlib import suppress
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


_control_address = ""

# kitty's remote control protocol: one escape-code framed JSON message each
# way. https://sw.kovidgoyal.net/kitty/rc_protocol/
CONTROL_PREFIX = b"\x1bP@kitty-cmd"
CONTROL_SUFFIX = b"\x1b\\"
CONTROL_TIMEOUT = 5.0

_kitty_version: list[int] = []
_control_lock = threading.Lock()


def kitty_version() -> list[int]:
    """The version to stamp on protocol messages, asked of kitten once."""
    if _kitty_version:
        return _kitty_version
    version = [0, 42, 0]
    try:
        result = subprocess.run(
            ["kitten", "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
        if match:
            version = [int(part) for part in match.groups()]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    _kitty_version.extend(version)
    return _kitty_version


class ControlSocket:
    """A held connection to the socket ``kitten @`` opens and closes each time.

    Most of a ``kitten @`` call is the process, not the work: a screen it
    fetches in 39ms comes back over an open socket in half of one. Only the two
    commands a poller repeats are hand-rolled here — everything else stays on
    the CLI, which knows how to turn arguments into payloads for every command
    kitty has.
    """

    def __init__(self, address: str) -> None:
        self.address = address
        self.sock: socket.socket | None = None

    def endpoint(self) -> str | None:
        if not self.address.startswith("unix:"):
            return None
        path = self.address.removeprefix("unix:")
        # @name is an abstract socket, which python spells with a leading NUL.
        return "\0" + path[1:] if path.startswith("@") else path

    def connect(self) -> socket.socket | None:
        if self.sock is not None:
            return self.sock
        endpoint = self.endpoint()
        if endpoint is None:
            return None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(CONTROL_TIMEOUT)
            sock.connect(endpoint)
        except OSError:
            return None
        self.sock = sock
        return sock

    def call(self, cmd: str, payload: dict[str, object]) -> object | None:
        """A command's ``data``, or None if the socket could not answer it.

        Any failure drops the connection rather than being reasoned about: this
        call falls back to the CLI and the next one reconnects. kitty documents
        a connection per query, so a held one is a courtesy it extends rather
        than a promise it makes.
        """
        sock = self.connect()
        if sock is None:
            return None
        message = {"cmd": cmd, "version": kitty_version(), "payload": payload}
        try:
            sock.sendall(CONTROL_PREFIX + json.dumps(message).encode() + CONTROL_SUFFIX)
            buffer = b""
            while CONTROL_SUFFIX not in buffer:
                chunk = sock.recv(65536)
                if not chunk:
                    raise OSError("kitty closed the control socket")
                buffer += chunk
            body = buffer.split(b"@kitty-cmd", 1)[1].rsplit(CONTROL_SUFFIX, 1)[0]
            response = json.loads(body)
        except (OSError, ValueError, IndexError):
            self.close()
            return None
        return response.get("data") if response.get("ok") else None

    def close(self) -> None:
        if self.sock is not None:
            with suppress(OSError):
                self.sock.close()
        self.sock = None


_control: ControlSocket | None = None


def control() -> ControlSocket | None:
    """The held socket, built from whichever address this process can reach."""
    global _control
    if _control is None:
        address = _control_address or child_listen_on()
        if not address.startswith("unix:"):
            return None
        _control = ControlSocket(address)
    return _control


def rc(cmd: str, payload: dict[str, object]) -> object | None:
    """One remote control command, or None to say ask the CLI instead.

    Serialised: one connection can only have one message in flight, and the
    pollers run in threads of their own.
    """
    client = control()
    if client is None:
        return None
    with _control_lock:
        return client.call(cmd, payload)




def use_control_address(address: str) -> None:
    """Send every later ``kitten @`` to this instance rather than our own.

    A client kitty launched inherits a socket; one you ssh in and start has to
    be told which instance it is looking at.
    """
    global _control_address, _control
    _control_address = address
    if _control is not None:
        _control.close()
    _control = None


def address_args() -> list[str]:
    return ["--to", _control_address] if _control_address else []


def kitty_pids() -> list[int]:
    """Pids of the running kitty instances, newest first."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "kitty"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except FileNotFoundError:
        return []
    pids = [int(line) for line in result.stdout.split() if line.isdigit()]
    return sorted(pids, reverse=True)


def socket_for_pid(pid: int) -> str:
    """The address os-${KITTY_OS}.conf gives an instance with this pid."""
    if sys.platform == "darwin":
        return f"unix:/tmp/mykitty-{pid}"
    return f"unix:@kitty-{pid}"


def discover_control_address() -> str:
    """An address for a running kitty, found rather than inherited.

    Prefers whatever this process was handed, which is right when the client
    runs inside kitty. Outside it — over ssh, or served to a browser — the
    sockets are named after the pid, so the running instances can be tried in
    turn and the first one that answers wins.
    """
    listen_on = os.environ.get("KITTY_LISTEN_ON", "")
    if listen_on and not listen_on.startswith("fd:"):
        return listen_on

    for pid in kitty_pids():
        address = socket_for_pid(pid)
        try:
            probe = subprocess.run(
                ["kitten", "@", "--to", address, "ls"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""
        if probe.returncode == 0:
            return address
    return ""


def run_kitten(*args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["kitten", "@", *address_args(), *args],
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
    data = rc("ls", {})
    if isinstance(data, str):
        with suppress(json.JSONDecodeError):
            return json.loads(data)

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


def screen_text(window_id: int | str, *, ansi: bool) -> str | None:
    """What is on one window's screen right now."""
    data = rc("get-text", {"match": f"id:{window_id}", "extent": "screen", "ansi": ansi})
    if isinstance(data, str):
        return data

    args = ["get-text", "--match", f"id:{window_id}", "--extent", "screen"]
    if ansi:
        args.append("--ansi")
    result = run_kitten(*args)
    if result is None or result.returncode != 0:
        return None
    return result.stdout


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
