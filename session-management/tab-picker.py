#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import json
import os
import subprocess
import sys
from dataclasses import dataclass


FZF_UI_ARGS = [
    "--layout",
    "reverse",
    "--height",
    "85%",
    "--border",
    "none",
    "--input-border",
    "rounded",
    "--list-border",
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


def emit(message: str, *, stderr: bool = False) -> None:
    stream = sys.stderr if stderr else sys.stdout
    print(message, file=stream)


def close_launcher_window(window_id: str | None) -> None:
    if not window_id:
        return
    subprocess.run(
        ["kitty", "@", "close-window", "--match", f"id:{window_id}"],
        check=False,
    )


def run_kitten(*args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["kitten", "@", *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        emit("tab-picker: kitten command not found", stderr=True)
        return None


def select_item(
    candidates: str,
    prompt: str,
    *,
    ansi: bool,
    extra_args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> tuple[str, int]:
    try:
        command = [
            "fzf",
            *FZF_UI_ARGS,
            "--no-sort",
            "--delimiter",
            "\t",
            "--with-nth",
            "1",
            "--prompt",
            prompt,
        ]
        if extra_args:
            command.extend(extra_args)
        if ansi:
            command.insert(1, "--ansi")
        proc = subprocess.run(
            command,
            input=candidates,
            stdout=subprocess.PIPE,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        emit("tab-picker: fzf command not found", stderr=True)
        return "", 1

    if proc.returncode != 0:
        return "", 2

    return proc.stdout.strip(), 0


@dataclass(frozen=True)
class PaneEntry:
    window_id: int
    title: str
    subtitle: str
    session: str
    is_focused: bool

    def render(self, *, show_session: bool, ansi: bool) -> str:
        focused_prefix = "* " if self.is_focused else "  "
        base = f"{focused_prefix}{self.title} - {self.subtitle}"
        if not show_session:
            return base
        session_label = self.session or "no session"
        if ansi:
            session_label = f"\x1b[2;36m[{session_label}]\x1b[0m"
        else:
            session_label = f"[{session_label}]"
        return f"{base}  {session_label}"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tab-picker",
        description="Focus an open kitty pane via fzf.",
    )
    parser.add_argument("--ansi", action="store_true", help="Enable ANSI in fzf")
    parser.add_argument(
        "--auto-close",
        action="store_true",
        help="Close the picker window on exit",
    )
    parser.add_argument(
        "--scope",
        choices=("session", "all"),
        default="session",
        help="Limit panes to current zoxide session or show all",
    )
    parser.add_argument(
        "--toggle-transform",
        action="store_true",
        help="Emit fzf transform output to toggle scope (for fzf bind)",
    )
    return parser.parse_args(argv[1:])


def clean_title(value: object) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return ""


def build_subtitle(tab: dict[str, object], window: dict[str, object]) -> str:
    parts: list[str] = []

    tab_title = clean_title(tab.get("title"))
    if tab_title:
        parts.append(tab_title)

    cwd = window.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        parts.append(cwd.strip())

    if not parts:
        parts.append(f"tab {tab.get('id', '?')}")

    return " | ".join(parts) if parts else "untitled"


SESSION_MARKER_VAR = "kitty_zoxide_session"
SESSION_SUFFIXES = (".kitty-session", ".kitty_session", ".session")


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


def tab_session_name(tab: dict[str, object]) -> str:
    name = normalize_session_name(tab.get("session_name"))
    if name:
        return name
    windows = tab.get("windows")
    if isinstance(windows, list):
        for window in windows:
            if not isinstance(window, dict):
                continue
            user_vars = window.get("user_vars")
            if not isinstance(user_vars, dict):
                continue
            name = normalize_session_name(user_vars.get(SESSION_MARKER_VAR))
            if name:
                return name
    return ""


def overlay_parent_ids(tab: dict[str, object]) -> set[int]:
    tab_windows = tab.get("windows")
    if not isinstance(tab_windows, list):
        return set()
    self_id: int | None = None
    for w in tab_windows:
        if isinstance(w, dict) and w.get("is_self"):
            wid = w.get("id")
            if isinstance(wid, int):
                self_id = wid
                break
    if self_id is None:
        return set()
    groups = tab.get("groups")
    if not isinstance(groups, list):
        return set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        win_ids = group.get("windows")
        if not isinstance(win_ids, list) or self_id not in win_ids:
            continue
        return {wid for wid in win_ids if isinstance(wid, int) and wid != self_id}
    return set()


def extract_panes(
    data: object, *, session_tab_ids: set[int] | None = None
) -> list[PaneEntry]:
    entries: list[PaneEntry] = []
    if not isinstance(data, list):
        return entries

    for os_window in data:
        if not isinstance(os_window, dict):
            continue
        tabs = os_window.get("tabs")
        if not isinstance(tabs, list):
            continue

        for tab in tabs:
            if not isinstance(tab, dict):
                continue

            tab_id = tab.get("id")
            if session_tab_ids is not None and (
                not isinstance(tab_id, int) or tab_id not in session_tab_ids
            ):
                continue

            session = tab_session_name(tab)

            tab_windows = tab.get("windows")
            if not isinstance(tab_windows, list):
                continue

            overlay_parents = overlay_parent_ids(tab)

            for window in tab_windows:
                if not isinstance(window, dict) or window.get("is_self"):
                    continue

                window_id = window.get("id")
                if not isinstance(window_id, int):
                    continue

                title = clean_title(window.get("title"))
                if not title:
                    title = f"pane {window_id}"

                is_focused = (
                    bool(window.get("is_focused")) or window_id in overlay_parents
                )

                entries.append(
                    PaneEntry(
                        window_id=window_id,
                        title=title,
                        subtitle=build_subtitle(tab, window),
                        session=session,
                        is_focused=is_focused,
                    )
                )

    return entries


def load_kitty_state(*extra_args: str) -> object | None:
    result = run_kitten("ls", *extra_args)
    if result is None:
        return None
    if result.returncode != 0:
        error = result.stderr.strip() or "failed to query kitty state"
        emit(f"tab-picker: {error}", stderr=True)
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        emit(f"tab-picker: failed to parse kitty state ({exc})", stderr=True)
        return None


def collect_tab_ids(data: object) -> set[int]:
    ids: set[int] = set()
    if not isinstance(data, list):
        return ids
    for os_window in data:
        if not isinstance(os_window, dict):
            continue
        tabs = os_window.get("tabs")
        if not isinstance(tabs, list):
            continue
        for tab in tabs:
            if isinstance(tab, dict):
                tab_id = tab.get("id")
                if isinstance(tab_id, int):
                    ids.add(tab_id)
    return ids


def focus_pane(window_id: int) -> int:
    result = run_kitten("focus-window", "--match", f"id:{window_id}")
    if result is None:
        return 1
    if result.returncode != 0:
        error = result.stderr.strip() or f"failed to focus pane {window_id}"
        emit(f"tab-picker: {error}", stderr=True)
    return result.returncode


PROMPT_SESSION = "session panes > "
PROMPT_ALL = "all panes > "


def build_candidates(panes: list[PaneEntry], *, scope: str, ansi: bool) -> str:
    show_session = scope == "all"
    return "\n".join(
        f"{pane.render(show_session=show_session, ansi=ansi)}\t{pane.window_id}"
        for pane in panes
    )


SESSION_ENV = "KITTY_TAB_PICKER_SESSION"
ALL_ENV = "KITTY_TAB_PICKER_ALL"


def build_toggle_bind(script_path: str) -> str:
    return f'ctrl-w:transform:python3 "{script_path}" --toggle-transform'


def emit_toggle_action() -> None:
    current_prompt = os.environ.get("FZF_PROMPT", "")
    if current_prompt == PROMPT_SESSION:
        next_prompt = PROMPT_ALL
        next_var = ALL_ENV
    else:
        next_prompt = PROMPT_SESSION
        next_var = SESSION_ENV
    reload_cmd = f'printf %s "${next_var}"'
    sys.stdout.write(f"change-prompt({next_prompt})+reload({reload_cmd})")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    script_path = os.path.abspath(sys.argv[0])

    if args.toggle_transform:
        emit_toggle_action()
        return 0

    launcher_window_id = os.environ.get("KITTY_WINDOW_ID")
    if args.auto_close:
        atexit.register(close_launcher_window, launcher_window_id)

    data = load_kitty_state()
    if data is None:
        return 1

    session_data = load_kitty_state("--match-tab", "session:.")
    session_tab_ids = (
        collect_tab_ids(session_data) if session_data is not None else set()
    )

    all_panes = extract_panes(data, session_tab_ids=None)
    session_panes = (
        extract_panes(data, session_tab_ids=session_tab_ids)
        if session_tab_ids
        else all_panes
    )

    if not all_panes:
        emit("tab-picker: no open panes found", stderr=True)
        return 1

    if args.scope == "session" and not session_panes:
        args.scope = "all"

    session_candidates = build_candidates(session_panes, scope="session", ansi=args.ansi)
    all_candidates = build_candidates(all_panes, scope="all", ansi=args.ansi)

    prompt = PROMPT_SESSION if args.scope == "session" else PROMPT_ALL
    toggle_bind = build_toggle_bind(script_path)
    extra_args = [
        "--bind",
        toggle_bind,
        "--header",
        "ctrl-w: toggle session/all",
    ]

    fzf_env = os.environ.copy()
    fzf_env[SESSION_ENV] = session_candidates
    fzf_env[ALL_ENV] = all_candidates

    candidates = session_candidates if args.scope == "session" else all_candidates
    selection, selection_status = select_item(
        candidates,
        prompt,
        ansi=args.ansi,
        extra_args=extra_args,
        env=fzf_env,
    )
    if selection_status != 0:
        return selection_status
    if not selection:
        emit("tab-picker: no pane selected", stderr=True)
        return 1

    _, _, window_id_text = selection.rpartition("\t")
    try:
        window_id = int(window_id_text)
    except ValueError:
        emit("tab-picker: selected pane could not be resolved", stderr=True)
        return 1

    return focus_pane(window_id)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
