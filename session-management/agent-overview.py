#!/usr/bin/env python3
"""Overview of every agent running in kitty, grouped by session.

Left: one row per agent — attention marker, status, agent, how long it has been
in that state, branch, and the tab title (which is where Claude Code writes what
it is currently doing). Right: that agent's actual screen, so the preview shows
real progress rather than a summary of it.

The list refreshes itself: fzf listens on a local port and a ticker in this
process posts reload actions to it, so statuses and ages stay current while the
overview is open.

Modes: no arguments runs the picker; --list prints the fzf input (used for
reloads); --screen ID prints the preview for one window.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shlex
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

from agents import (
    Agent,
    child_listen_on,
    clear_attention,
    collect_agents,
    color,
    group_by_session,
    kitty_state,
    run_kitten,
    status_counts,
)

SCRIPT = str(Path(__file__).resolve())
REFRESH_SECONDS = 2.0

FZF_UI_ARGS = [
    "--layout",
    "reverse",
    "--height",
    "100%",
    "--border",
    "none",
    "--input-border",
    "rounded",
    "--list-border",
    "rounded",
    "--preview-border",
    "rounded",
    "--header-border",
    "none",
    "--margin",
    "0",
    "--info",
    "inline-right",
    "--separator",
    "",
    "--scrollbar",
    "▌",
]


def row(agent: Agent, *, ansi: bool) -> str:
    """One agent, as ``display \\t session \\t window id``.

    Session rides along in its own field so filtering by it still matches rows
    once the group header has been filtered away.
    """
    marker = color("!", "1;33", ansi=ansi) if agent.has_attention else " "
    status = color(f"{agent.dot} {agent.status:<8}", agent.status_color, ansi=ansi)
    name = color(f"{agent.agent:<9}", "1;36", ansi=ansi)
    age = color(f"{agent.age:>4}", "2;37", ansi=ansi)
    branch = color(f"{agent.branch[:18]:<18}", "35", ansi=ansi)
    display = f"  {marker} {status} {name} {age}  {branch} {agent.title}"
    return f"{display}\t{agent.session}\t{agent.window_id}"


def header_row(session: str, agents: list[Agent], *, ansi: bool) -> str:
    """A session header. Selecting it focuses that session's first agent."""
    label = color(session or "no session", "1;37", ansi=ansi)
    count = color(f"{len(agents)}", "2;37", ansi=ansi)
    return f"{label} {count}\t{session}\t{agents[0].window_id}"


def header_line() -> str:
    agents = collect_agents(kitty_state())
    counts = status_counts(agents) or "none"
    plural = "" if len(agents) == 1 else "s"
    return (
        f"{len(agents)} agent{plural} · {counts}"
        "    Enter focus  Ctrl-X clear attention  Ctrl-R refresh"
    )


def list_lines(*, ansi: bool) -> list[str]:
    agents = collect_agents(kitty_state())
    if not agents:
        return []

    lines: list[str] = []
    for index, (session, group) in enumerate(group_by_session(agents)):
        if index:
            lines.append(f" \t{session}\t{group[0].window_id}")
        lines.append(header_row(session, group, ansi=ansi))
        lines.extend(row(agent, ansi=ansi) for agent in group)
    return lines


def screen_of(window_id: str, *, ansi: bool) -> int:
    """Print one agent's screen, headed by what and where it is."""
    agent = next(
        (
            candidate
            for candidate in collect_agents(kitty_state())
            if str(candidate.window_id) == str(window_id)
        ),
        None,
    )
    if agent is not None:
        where = " · ".join(filter(None, [agent.agent, agent.session, agent.branch]))
        age = f" · {agent.age}" if agent.age else ""
        print(color(f"{agent.dot} {agent.status}", agent.status_color, ansi=ansi), end=" ")
        print(color(f"{where}{age}", "2;37", ansi=ansi))
        print(color("─" * 60, "2;37", ansi=ansi))

    args = ["get-text", "--match", f"id:{window_id}", "--extent", "screen"]
    if ansi:
        args.append("--ansi")
    result = run_kitten(*args)
    if result is None or result.returncode != 0:
        print("(could not read this window)")
        return 0

    # kitty pads the screen out to its height; trailing blank rows would push
    # the interesting part out of view.
    print("\n".join(result.stdout.rstrip("\n").splitlines()))
    return 0


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def post_action(port: int, action: str) -> None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}", data=action.encode("utf-8"), method="POST"
    )
    with contextlib.suppress(urllib.error.URLError, OSError):
        urllib.request.urlopen(request, timeout=1).close()


def ticker(port: int, action: str, done: threading.Event) -> None:
    """Nudge fzf to reload while the overview is open, so ages keep counting."""
    while not done.wait(REFRESH_SECONDS):
        post_action(port, action)


def run_picker(*, ansi: bool) -> int:
    lines = list_lines(ansi=ansi)
    if not lines:
        print("No agents running")
        return 0

    quoted = shlex.quote(SCRIPT)
    list_command = f"python3 {quoted} --list" + (" --ansi" if ansi else "")
    preview_command = f"python3 {quoted} --screen {{3}}" + (" --ansi" if ansi else "")
    port = free_port()

    fzf_command = [
        "fzf",
        *FZF_UI_ARGS,
        "--no-sort",
        "--expect",
        "enter,ctrl-x",
        "--delimiter",
        "\t",
        "--with-nth",
        "1",
        "--nth",
        "1,2",
        "--listen",
        f"127.0.0.1:{port}",
        "--preview",
        preview_command,
        "--preview-window",
        "right,55%,border-rounded",
        "--bind",
        f"ctrl-r:reload({list_command})+refresh-preview",
        # Counts and ages go stale as fast as the list does, so rebuild the
        # header whenever the results change — which the ticker's reloads do.
        "--bind",
        f"result:transform-header(python3 {quoted} --header)",
        "--header",
        header_line(),
        "--prompt",
        "agents > ",
    ]
    if ansi:
        fzf_command.insert(1, "--ansi")

    done = threading.Event()
    refresh = threading.Thread(
        target=ticker,
        args=(port, f"reload({list_command})+refresh-preview", done),
        daemon=True,
    )

    # fzf's preview and reload commands are grandchildren of this process, so
    # hand them an address they can open themselves.
    env = dict(os.environ)
    if address := child_listen_on():
        env["KITTY_LISTEN_ON"] = address

    try:
        refresh.start()
        proc = subprocess.run(
            fzf_command,
            input="\n".join(lines),
            stdout=subprocess.PIPE,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        print("agent-overview: fzf command not found", file=sys.stderr)
        return 1
    finally:
        done.set()

    if proc.returncode != 0:
        return 0

    output = proc.stdout.splitlines()
    if len(output) < 2:
        return 0

    key = output[0].strip()
    _, _, raw_window_id = output[1].rpartition("\t")
    try:
        window_id = int(raw_window_id)
    except ValueError:
        return 0

    if key == "ctrl-x":
        return clear_attention(window_id)

    result = run_kitten("focus-window", "--match", f"id:{window_id}")
    return 1 if result is None else result.returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Overview of every agent running in kitty.")
    parser.add_argument("--ansi", action="store_true", help="Enable ANSI formatting")
    parser.add_argument("--list", action="store_true", help="Print the fzf input and exit")
    parser.add_argument("--screen", metavar="WINDOW_ID", help="Print one agent's screen and exit")
    parser.add_argument("--header", action="store_true", help="Print the header line and exit")
    args = parser.parse_args(argv[1:])

    if args.header:
        print(header_line())
        return 0
    if args.screen:
        return screen_of(args.screen, ansi=args.ansi)
    if args.list:
        print("\n".join(list_lines(ansi=args.ansi)))
        return 0
    return run_picker(ansi=args.ansi)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
