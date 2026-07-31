#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys


FD_RE = re.compile(r"fd:(\d+)")


def emit(message: str) -> None:
    print(message, file=sys.stderr)


def kitten_pass_fds() -> tuple[int, ...]:
    listen_on = os.environ.get("KITTY_LISTEN_ON", "")
    match = FD_RE.search(listen_on)
    if match is None:
        return ()
    return (int(match.group(1)),)


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
        emit("focus-or-launch-tool-tab: kitten command not found")
        return None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="focus-or-launch-tool-tab",
        description="Focus a tool tab in the current kitty OS window or open it.",
    )
    parser.add_argument("tool", help="Command to launch, e.g. lazygit")
    parser.add_argument(
        "--title",
        help="Stable title to use for matching and for the launched tab/window",
    )
    parser.add_argument(
        "--global",
        dest="global_tool",
        action="store_true",
        help="Launch without adding the tab to the current kitty session",
    )
    return parser.parse_args(argv[1:])


def source_window_id() -> int | None:
    value = os.environ.get("KITTY_WINDOW_ID")
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def source_window_match(window_id: int) -> str:
    return f"id:{window_id}"


def kitty_state() -> object | None:
    result = run_kitten("ls")
    if result is None or result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def find_tab_in_current_os_window(title: str, target_window_id: int) -> int | None:
    state = kitty_state()
    if not isinstance(state, list):
        return None

    for os_window in state:
        if not isinstance(os_window, dict):
            continue
        tabs = os_window.get("tabs")
        if not isinstance(tabs, list):
            continue

        in_current_os_window = False
        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            windows = tab.get("windows")
            if not isinstance(windows, list):
                continue
            if any(
                isinstance(window, dict) and window.get("id") == target_window_id
                for window in windows
            ):
                in_current_os_window = True
                break

        if not in_current_os_window:
            continue

        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            tab_id = tab.get("id")
            tab_title = tab.get("title")
            if (
                isinstance(tab_id, int)
                and isinstance(tab_title, str)
                and tab_title == title
            ):
                return tab_id

        return None

    return None


def focus_existing(title: str) -> int:
    window_id = source_window_id()
    if window_id is None:
        emit("focus-or-launch-tool-tab: KITTY_WINDOW_ID not available")
        return 1

    tab_id = find_tab_in_current_os_window(title, window_id)
    if tab_id is None:
        return 1
    result = run_kitten("focus-tab", "--match", f"id:{tab_id}")
    if result is None:
        return 1
    if result.returncode == 0:
        return 0
    return result.returncode


def tool_color_args(tool: str) -> list[str]:
    if tool not in {"lazygit", "lazydocker"}:
        return []
    return [
        "--color=color4=#524f67",
        "--color=color8=#403d52",
    ]


def launch_tool(tool: str, title: str, *, global_tool: bool) -> int:
    window_id = source_window_id()
    if window_id is None:
        emit("focus-or-launch-tool-tab: KITTY_WINDOW_ID not available")
        return 1

    source_window = source_window_match(window_id)
    session_args = ["--add-to-session=!"] if global_tool else ["--add-to-session=."]

    result = run_kitten(
        "launch",
        f"--source-window={source_window}",
        "--type=tab",
        "--cwd=current",
        *session_args,
        f"--tab-title={title}",
        f"--title={title}",
        *tool_color_args(tool),
        tool,
    )
    if result is None:
        return 1
    if result.returncode != 0:
        error = result.stderr.strip() or f"failed to launch {tool}"
        emit(f"focus-or-launch-tool-tab: {error}")
    return result.returncode


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    title = args.title or args.tool

    focus_status = focus_existing(title)
    if focus_status == 0:
        return 0

    return launch_tool(args.tool, title, global_tool=args.global_tool)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
