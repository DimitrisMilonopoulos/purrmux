#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path


SESSION_MARKER_VAR = "kitty_zoxide_session"
SESSION_SUFFIXES = (".kitty-session", ".kitty_session", ".session")
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
        emit("cycle-session: kitten command not found")
        return None


def normalize_session_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    name = os.path.basename(text)
    for suffix in SESSION_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    if "." in name:
        return name.rsplit(".", 1)[0]
    return name


def resolve_session_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    base_dir = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base_dir / "kitty-sessions"


def list_session_files(session_dir: Path) -> list[Path]:
    if not session_dir.exists():
        return []
    return sorted(session_dir.glob("*.kitty-session"))


def run_zoxide() -> str:
    try:
        result = subprocess.run(
            ["zoxide", "query", "-l"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def known_session_names(session_dir: Path) -> set[str]:
    names = {session_file.stem for session_file in list_session_files(session_dir)}
    names.update(name for path in run_zoxide().splitlines() if (name := Path(path).name))
    return names


def normalize_known_session_name(value: object, known_names: set[str]) -> str:
    name = normalize_session_name(value)
    return name if name in known_names else ""


def tab_session_name(tab: dict, known_names: set[str]) -> str:
    name = normalize_session_name(tab.get("session_name"))
    if name and name in known_names:
        return name
    windows = tab.get("windows")
    if isinstance(windows, list):
        for window in windows:
            if not isinstance(window, dict):
                continue
            user_vars = window.get("user_vars")
            if not isinstance(user_vars, dict):
                continue
            name = normalize_known_session_name(
                user_vars.get(SESSION_MARKER_VAR), known_names
            )
            if name:
                return name
    name = normalize_known_session_name(tab.get("title"), known_names)
    if name:
        return name
    return ""


def load_state() -> object | None:
    result = run_kitten("ls")
    if result is None or result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def collect_sessions(
    data: object, known_names: set[str]
) -> "OrderedDict[str, list[dict]]":
    sessions: "OrderedDict[str, list[dict]]" = OrderedDict()
    if not isinstance(data, list):
        return sessions
    for os_window in data:
        if not isinstance(os_window, dict):
            continue
        tabs = os_window.get("tabs")
        if not isinstance(tabs, list):
            continue
        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            session = tab_session_name(tab, known_names)
            if not session:
                continue
            tab_id = tab.get("id")
            if not isinstance(tab_id, int):
                continue
            sessions.setdefault(session, []).append(
                {
                    "id": tab_id,
                    "is_active": bool(tab.get("is_active")),
                    "is_focused": bool(tab.get("is_focused")),
                }
            )
    return sessions


def current_session_name(data: object, known_names: set[str]) -> str:
    if not isinstance(data, list):
        return ""
    for os_window in data:
        if not isinstance(os_window, dict):
            continue
        tabs = os_window.get("tabs")
        if not isinstance(tabs, list):
            continue
        for tab in tabs:
            if isinstance(tab, dict) and tab.get("is_focused"):
                return tab_session_name(tab, known_names)
    return ""


def goto_session(session_file: Path) -> int:
    result = run_kitten("action", "goto_session", str(session_file))
    if result is None:
        return 1
    if result.returncode != 0:
        error = result.stderr.strip() or f"failed to go to session '{session_file.stem}'"
        emit(f"cycle-session: {error}")
    return result.returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cycle-session")
    parser.add_argument(
        "--prev", action="store_true", help="Cycle to the previous session"
    )
    args = parser.parse_args(argv[1:])

    data = load_state()
    if data is None:
        emit("cycle-session: failed to query kitty state")
        return 1

    session_dir = resolve_session_dir()
    known_names = known_session_names(session_dir)
    sessions = collect_sessions(data, known_names)
    if not sessions:
        emit("cycle-session: no sessions found")
        return 1

    names = [
        name
        for name in sessions.keys()
        if (session_dir / f"{name}.kitty-session").exists()
    ]
    if len(names) < 2:
        return 0

    current = current_session_name(data, known_names)
    if current in names:
        idx = names.index(current)
        step = -1 if args.prev else 1
        next_name = names[(idx + step) % len(names)]
    else:
        next_name = names[-1] if args.prev else names[0]

    session_file = session_dir / f"{next_name}.kitty-session"
    if not session_file.exists():
        emit(f"cycle-session: no session file for '{next_name}'")
        return 1

    return goto_session(session_file)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
