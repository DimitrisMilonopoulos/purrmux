#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import glob
import json
import logging
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


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


LOGGER = logging.getLogger("kitty-zoxide-sessions")
SESSION_ENTRY = "session"
PATH_ENTRY = "path"
GENERATED_TEMPLATE_MARKER = "# managed-by: kitty-zoxide-sessions\n"
SESSION_MARKER_VAR = "kitty_zoxide_session"
LEGACY_DEFAULT_TEMPLATE = """new_tab @@session@@
cd @@session-path@@ 
launch --title \"@@session@@\"

new_tab @@session@@
cd @@session-path@@ 
launch --title \"@@session@@\"
"""


def close_launcher_window(window_id: str | None) -> None:
    if not window_id:
        return
    subprocess.run(
        ["kitty", "@", "close-window", "--match", f"id:{window_id}"],
        check=False,
    )


def run_kitten(
    *args: str, to: str | None = None
) -> subprocess.CompletedProcess[str] | None:
    command = ["kitten", "@"]
    if to:
        command += ["--to", to]
    command += list(args)
    try:
        return subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        emit("kitty-zoxide-sessions: kitten command not found", stderr=True)
        return None


MAIN_LISTEN_ON_ENV = "KITTY_MAIN_LISTEN_ON"


def discover_main_listen_on(self_pid: int | None) -> str | None:
    """Find the remote-control socket of the main kitty instance.

    The picker may run inside the quick-access dropdown, which is its own kitty
    process. Sessions must be created/focused in the *main* instance, so its
    socket has to be resolved explicitly rather than using the ambient
    ``$KITTY_LISTEN_ON`` (which points at the dropdown).
    """
    candidates: list[tuple[int, str]] = []

    # Linux: abstract sockets show up in /proc/net/unix as ``@kitty-<pid>``.
    try:
        with open("/proc/net/unix", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                name = line.rstrip("\n").rsplit(" ", 1)[-1]
                match = re.fullmatch(r"@kitty-(\d+)", name)
                if match:
                    candidates.append((int(match.group(1)), f"unix:{name}"))
    except OSError:
        pass

    # macOS / file-based sockets: ``listen_on unix:/tmp/mykitty-<pid>``.
    if not candidates:
        for path in glob.glob("/tmp/mykitty-*"):
            match = re.fullmatch(r".*/mykitty-(\d+)", path)
            if match:
                candidates.append((int(match.group(1)), f"unix:{path}"))

    others = [addr for pid, addr in candidates if pid != self_pid]
    pool = others or [addr for _, addr in candidates]

    if not pool:
        return None
    if len(pool) > 1:
        emit(
            "kitty-zoxide-sessions: multiple kitty instances found; "
            f"using {pool[0]}. Set {MAIN_LISTEN_ON_ENV} to disambiguate.",
            stderr=True,
        )
    return pool[0]


def resolve_main_listen_on(value: str | None) -> str | None:
    """Turn the --main-listen-on value (or env override) into a socket address."""
    value = value or os.environ.get(MAIN_LISTEN_ON_ENV)
    if not value:
        return None
    if value == "auto":
        self_pid_raw = os.environ.get("KITTY_PID", "")
        self_pid = int(self_pid_raw) if self_pid_raw.isdigit() else None
        return discover_main_listen_on(self_pid)
    return value


def setup_logging(log_dir: Path) -> None:
    if LOGGER.handlers:
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "kitty-zoxide-sessions.log"

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.propagate = False


def emit(message: str, *, stderr: bool = False) -> None:
    stream = sys.stderr if stderr else sys.stdout
    print(message, file=stream)
    if stderr:
        LOGGER.error(message)
    else:
        LOGGER.info(message)


SESSION_SUFFIXES = (".kitty-session", ".kitty_session", ".session")


def log(message: str, enabled: bool) -> None:
    if enabled:
        LOGGER.debug(message)


def normalize_session_name(value: object) -> str:
    if not isinstance(value, str):
        return ""

    text = value.strip()
    if not text:
        return ""

    name = Path(text).name
    for suffix in SESSION_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem if "." in name else name


def git_branch(path: str | None) -> str | None:
    """Return the current branch (or short SHA) for the repo at ``path``.

    Reads ``.git/HEAD`` directly instead of shelling out to ``git`` so this stays
    cheap enough to call for every picker entry. Handles the worktree/submodule
    case where ``.git`` is a file pointing at the real git dir.
    """
    if not path:
        return None

    git_dir = Path(path).expanduser() / ".git"

    if git_dir.is_file():
        try:
            pointer = git_dir.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not pointer.startswith("gitdir:"):
            return None
        resolved = pointer[len("gitdir:") :].strip()
        git_dir = Path(resolved)
        if not git_dir.is_absolute():
            git_dir = (Path(path).expanduser() / git_dir).resolve()

    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/") :]
    if head:
        return head[:7]
    return None


def resolve_session_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    base_dir = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base_dir / "kitty-sessions"


def select_item(candidates: str, prompt: str, *, ansi: bool) -> tuple[str, int]:
    try:
        fzf_command = ["fzf", *FZF_UI_ARGS, "--no-sort", "--prompt", prompt]
        if ansi:
            fzf_command.insert(1, "--ansi")
        proc = subprocess.run(
            fzf_command,
            input=candidates,
            stdout=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        emit("kitty-zoxide-sessions: fzf command not found", stderr=True)
        return "", 1

    if proc.returncode != 0:
        return "", 2

    return proc.stdout.strip(), 0


def select_structured_item(
    candidates: str, prompt: str, *, ansi: bool
) -> tuple[str, str, int]:
    try:
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
            "--header",
            "Enter open  Ctrl-X close open session",
            "--prompt",
            prompt,
        ]
        if ansi:
            fzf_command.insert(1, "--ansi")
        proc = subprocess.run(
            fzf_command,
            input=candidates,
            stdout=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        emit("kitty-zoxide-sessions: fzf command not found", stderr=True)
        return "", "", 1

    if proc.returncode != 0:
        return "", "", 2

    lines = proc.stdout.splitlines()
    if not lines:
        return "", "", 0

    key = lines[0].strip()
    selection = lines[1].strip() if len(lines) > 1 else ""
    return key, selection, 0


def list_session_files(session_dir: Path) -> list[Path]:
    if not session_dir.exists():
        return []

    return sorted(session_dir.glob("*.kitty-session"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kitty-zoxide-sessions",
        description="Launch a kitty session from zoxide entries.",
        epilog=(
            "For more information about kitty sessions visit: "
            "https://sw.kovidgoyal.net/kitty/sessions/"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d", "--debug", action="store_true", help="Enable debug logging"
    )
    parser.add_argument("-e", "--edit", action="store_true", help="Edit session file")
    parser.add_argument(
        "-D", "--delete", action="store_true", help="Delete a session file"
    )
    parser.add_argument(
        "--delete-all", action="store_true", help="Delete all session files"
    )
    parser.add_argument(
        "--ansi", action="store_true", help="Enable ANSI formatting in fzf"
    )
    parser.add_argument(
        "-c",
        "--auto-close",
        action="store_true",
        help="Close window on selection",
    )
    parser.add_argument(
        "-t",
        "--template",
        help="Path to a custom kitty session template",
    )
    parser.add_argument(
        "--target",
        choices=("window", "tab"),
        default="tab",
        help=(
            "Open the session in a new OS window or as a tab in the "
            "current window (default: tab)"
        ),
    )
    parser.add_argument(
        "--main-listen-on",
        default=None,
        help=(
            "Remote-control socket of the main kitty instance to drive "
            "(e.g. 'unix:@kitty-1234'), or 'auto' to discover it. Use this "
            "when running the picker inside the quick-access dropdown so "
            f"sessions open in the main instance. Overridable via {MAIN_LISTEN_ON_ENV}."
        ),
    )
    return parser


def parse_args(
    parser: argparse.ArgumentParser, argv: list[str]
) -> argparse.Namespace | int:
    try:
        return parser.parse_args(argv[1:])
    except SystemExit:
        return 1


@dataclass(frozen=True)
class AppContext:
    session_dir: Path
    parser: argparse.ArgumentParser
    debug: bool
    ansi: bool
    template_path: Path | None
    launcher_window_id: str | None
    target: str
    remote_to: str | None


@dataclass(frozen=True)
class SessionStats:
    is_open: bool
    is_active: bool
    tab_count: int
    pane_count: int


@dataclass(frozen=True)
class OpenSessionInfo:
    stats: SessionStats
    tab_ids: tuple[int, ...]
    active_tab_ids: tuple[int, ...]


@dataclass(frozen=True)
class PickerEntry:
    entry_type: str
    session_name: str
    session_file: Path
    session_path: str | None
    stats: SessionStats | None
    display_label: str
    selection_key: str


class Operation:
    def __init__(self, context: AppContext) -> None:
        self.context = context

    def run(self) -> int:
        raise NotImplementedError


class DeleteAllSessions(Operation):
    def confirm_delete_all(self) -> bool:
        emit("This will delete all kitty session files.")
        try:
            response = input("Type 'yes' to continue: ").strip().lower()
        except EOFError:
            return False

        return response == "yes"

    def run(self) -> int:
        session_files = list_session_files(self.context.session_dir)
        if not session_files:
            emit("kitty-zoxide-sessions: no session files to delete", stderr=True)
            return 1

        if not self.confirm_delete_all():
            emit("Delete all cancelled", stderr=True)
            return 1

        failed = False
        for session_file in session_files:
            try:
                session_file.unlink()
            except OSError as exc:
                emit(
                    f"kitty-zoxide-sessions: failed to delete session file '{session_file}' ({exc})",
                    stderr=True,
                )
                failed = True

        if failed:
            return 1

        msg = "Deleted all sessions files"
        emit(msg)
        log(msg, self.context.debug)
        return 0


class DeleteSession(Operation):
    def run(self) -> int:
        session_files = list_session_files(self.context.session_dir)
        if not session_files:
            emit("kitty-zoxide-sessions: no session files to delete", stderr=True)
            return 1

        candidates = "\n".join(path.stem for path in session_files)
        session_name, selection_status = select_item(
            candidates,
            "delete session > ",
            ansi=self.context.ansi,
        )
        if selection_status != 0:
            return selection_status

        if not session_name:
            emit("No session selected", stderr=True)
            emit(self.context.parser.format_help(), stderr=True)
            return 1

        session_file = self.context.session_dir / f"{session_name}.kitty-session"
        try:
            session_file.unlink()
        except OSError as exc:
            emit(
                f"kitty-zoxide-sessions: failed to delete session file '{session_file}' ({exc})",
                stderr=True,
            )
            return 1
        emit(f"Deleted session: {session_name}")
        log(f"Deleted session file: {session_file}", self.context.debug)
        return 0


class SessionSelection(Operation):
    def __init__(self, context: AppContext, *, editing: bool) -> None:
        super().__init__(context)
        self.editing = editing

    def handle_session(self, _session_file: Path) -> int:
        raise NotImplementedError

    def render_session_data(
        self, template: str, session_path: str, session_name: str
    ) -> str:
        open_directive = (
            "new_os_window" if self.context.target == "window" else "new_tab"
        )
        return (
            template.replace("@@open-directive@@", open_directive)
            .replace("@@session-path@@", session_path)
            .replace("@@session@@", session_name)
        )

    def session_data(
        self,
        session_path: str,
        session_name: str,
        template_path: Path | None,
    ) -> str | int:
        default_template = Path(__file__).with_name("default.kitty-session")

        template = None
        for candidate in [path for path in (template_path, default_template) if path]:
            try:
                template = candidate.read_text(encoding="utf-8")
                break
            except OSError as exc:
                emit(
                    f"kitty-zoxide-sessions: failed to read template file '{candidate}' ({exc})",
                    stderr=True,
                )

        if template is None:
            return 1

        return self.render_session_data(template, session_path, session_name)

    def is_managed_session_file(
        self,
        existing_data: str,
        session_path: str,
        session_name: str,
    ) -> bool:
        if existing_data.startswith(GENERATED_TEMPLATE_MARKER):
            return True

        legacy_data = self.render_session_data(
            LEGACY_DEFAULT_TEMPLATE, session_path, session_name
        )
        return existing_data == legacy_data

    def ensure_session_file(
        self,
        session_dir: Path,
        session_name: str,
        session_path: str,
        debug: bool,
        template_path: Path | None,
    ) -> Path | int:
        session_file = session_dir / f"{session_name}.kitty-session"

        data = self.session_data(session_path, session_name, template_path)
        if isinstance(data, int):
            return data

        if session_file.exists():
            try:
                existing_data = session_file.read_text(encoding="utf-8")
            except OSError as exc:
                emit(
                    f"kitty-zoxide-sessions: failed to read session file '{session_file}' ({exc})",
                    stderr=True,
                )
                return 1

            if existing_data == data:
                return session_file

            if not self.is_managed_session_file(
                existing_data, session_path, session_name
            ):
                return session_file

            log(f"Refreshing managed session file: {session_file}", debug)

        try:
            session_file.write_text(data, encoding="utf-8")
        except OSError as exc:
            emit(
                f"kitty-zoxide-sessions: failed to write session file ({exc})",
                stderr=True,
            )
            return 1

        log(f"Creating session file: {session_file}", debug)
        return session_file

    def run_zoxide(self) -> str | None:
        try:
            result = subprocess.run(
                ["zoxide", "query", "-l"],
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            emit("kitty-zoxide-sessions: zoxide command not found", stderr=True)
            return None
        except subprocess.CalledProcessError as exc:
            emit(
                f"kitty-zoxide-sessions: failed to query zoxide (exit code {exc.returncode})",
                stderr=True,
            )
            return None

        return result.stdout

    def color(self, text: str, code: str) -> str:
        if not self.context.ansi:
            return text
        return f"\x1b[{code}m{text}\x1b[0m"

    def icon(self, value: str, color_code: str | None = None) -> str:
        if color_code is None:
            return value
        return self.color(value, color_code)

    def shorten_path(self, value: str) -> str:
        path = Path(value).expanduser()
        home = Path.home()
        try:
            relative_to_home = path.relative_to(home)
            parts = list(relative_to_home.parts)
            prefix = "~"
        except ValueError:
            parts = list(path.parts)
            prefix = parts[0] if parts else str(path)
            parts = parts[1:] if parts else []

        if not parts:
            return prefix
        if len(parts) <= 2:
            return str(Path(prefix, *parts))
        return str(Path(prefix, *parts[-2:]))

    def infer_tab_session_name(
        self, tab: dict[str, object], known_session_names: set[str]
    ) -> str:
        session_name = normalize_session_name(tab.get("session_name"))
        if session_name:
            return session_name

        tab_windows = tab.get("windows")
        if isinstance(tab_windows, list):
            for window in tab_windows:
                if not isinstance(window, dict):
                    continue
                user_vars = window.get("user_vars")
                if not isinstance(user_vars, dict):
                    continue
                session_name = normalize_session_name(user_vars.get(SESSION_MARKER_VAR))
                if session_name:
                    return session_name

        title_name = normalize_session_name(tab.get("title"))
        if title_name in known_session_names:
            return title_name

        return ""

    def confirm_close(self, session_name: str, *, is_active: bool) -> bool:
        prompt = (
            f"Close active session '{session_name}'? [y/N]: "
            if is_active
            else f"Close session '{session_name}'? [y/N]: "
        )
        try:
            response = input(prompt).strip().lower()
        except EOFError:
            return False
        return response in {"y", "yes"}

    def close_open_session(
        self, session_name: str, session_info: OpenSessionInfo
    ) -> int:
        if not session_info.tab_ids:
            emit(
                f"kitty-zoxide-sessions: no open tabs found for session '{session_name}'",
                stderr=True,
            )
            return 1

        active_tab_ids = set(session_info.active_tab_ids)
        ordered_tab_ids = [
            tab_id for tab_id in session_info.tab_ids if tab_id not in active_tab_ids
        ] + [tab_id for tab_id in session_info.tab_ids if tab_id in active_tab_ids]

        for tab_id in ordered_tab_ids:
            result = run_kitten(
                "close-tab", "--match", f"id:{tab_id}", to=self.context.remote_to
            )
            if result is None:
                return 1
            if result.returncode != 0:
                error = result.stderr.strip() or f"failed to close tab {tab_id}"
                emit(f"kitty-zoxide-sessions: {error}", stderr=True)
                return result.returncode

        return 0

    def list_open_sessions(
        self, known_session_names: set[str]
    ) -> dict[str, OpenSessionInfo]:
        result = run_kitten("ls", to=self.context.remote_to)
        if result is None or result.returncode != 0:
            if result is not None:
                error = result.stderr.strip()
                if error and self.context.debug:
                    LOGGER.debug("Failed to query live kitty state: %s", error)
            return {}

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            log(f"Failed to parse kitty state: {exc}", self.context.debug)
            return {}

        aggregated: dict[str, dict[str, object]] = {}
        if not isinstance(data, list):
            return {}

        for os_window in data:
            if not isinstance(os_window, dict):
                continue
            tabs = os_window.get("tabs")
            if not isinstance(tabs, list):
                continue

            for tab in tabs:
                if not isinstance(tab, dict):
                    continue
                session_name = self.infer_tab_session_name(tab, known_session_names)
                if not session_name:
                    continue

                tab_id = tab.get("id")
                if not isinstance(tab_id, int):
                    continue

                tab_windows = tab.get("windows")
                pane_count = 0
                if isinstance(tab_windows, list):
                    pane_count += sum(
                        1
                        for window in tab_windows
                        if isinstance(window, dict) and not window.get("is_self")
                    )

                stats = aggregated.setdefault(
                    session_name,
                    {
                        "tab_count": 0,
                        "pane_count": 0,
                        "is_active": False,
                        "tab_ids": [],
                        "active_tab_ids": [],
                    },
                )
                stats["tab_count"] = int(stats["tab_count"]) + 1
                stats["pane_count"] = int(stats["pane_count"]) + pane_count
                tab_ids = stats.get("tab_ids")
                if isinstance(tab_ids, list):
                    tab_ids.append(tab_id)
                if bool(tab.get("is_focused")) or bool(tab.get("is_active")):
                    stats["is_active"] = True
                    active_tab_ids = stats.get("active_tab_ids")
                    if isinstance(active_tab_ids, list):
                        active_tab_ids.append(tab_id)

        return {
            session_name: OpenSessionInfo(
                stats=SessionStats(
                    is_open=True,
                    is_active=bool(values["is_active"]),
                    tab_count=int(values["tab_count"]),
                    pane_count=int(values["pane_count"]),
                ),
                tab_ids=tuple(
                    tab_id
                    for tab_id in values.get("tab_ids", [])
                    if isinstance(tab_id, int)
                ),
                active_tab_ids=tuple(
                    tab_id
                    for tab_id in values.get("active_tab_ids", [])
                    if isinstance(tab_id, int)
                ),
            )
            for session_name, values in aggregated.items()
        }

    def format_counts(self, stats: SessionStats) -> str:
        tabs = self.color("󰇘", "2;36")
        panes = self.color("󰖯", "2;36")
        counts = f"{tabs} {stats.tab_count}  {panes} {stats.pane_count}"
        return self.color(counts, "2") if self.context.ansi else counts

    def format_branch(self, branch: str | None) -> str:
        if not branch:
            return ""
        text = f" {branch}"
        return "  " + (self.color(text, "2;35") if self.context.ansi else text)

    def format_entry_label(
        self,
        entry_type: str,
        session_name: str,
        session_path: str | None,
        stats: SessionStats | None,
        branch: str | None = None,
    ) -> str:
        suffix = self.format_branch(branch)

        if stats is not None and stats.is_active:
            icon = self.icon("󰆍", "1;32")
            return f"{icon} {session_name}  {self.format_counts(stats)}{suffix}"

        if stats is not None and stats.is_open:
            icon = self.icon("󰖲", "1;34")
            return f"{icon} {session_name}  {self.format_counts(stats)}{suffix}"

        if entry_type == SESSION_ENTRY:
            icon = self.icon("󰆓", "1;33")
            return f"{icon} {session_name}{suffix}"

        icon = self.icon("󰉋", "1;35")
        path_context = self.shorten_path(session_path or session_name)
        context_text = self.color(path_context, "2;37")
        return f"{icon} {session_name}  {context_text}{suffix}"

    def sort_entries(self, entries: list[PickerEntry]) -> list[PickerEntry]:
        def rank(entry: PickerEntry) -> tuple[int, str]:
            stats = entry.stats
            if stats is not None and stats.is_active:
                return (0, entry.session_name)
            if stats is not None and stats.is_open:
                return (1, entry.session_name)
            if entry.entry_type == SESSION_ENTRY:
                return (2, entry.session_name)
            return (3, entry.session_name)

        return sorted(entries, key=rank)

    def build_entries(
        self,
        session_files: list[Path],
        zoxide_paths: list[str],
        open_sessions: dict[str, OpenSessionInfo],
    ) -> list[PickerEntry]:
        entries: list[PickerEntry] = []
        session_names = {session_file.stem for session_file in session_files}
        zoxide_by_name: dict[str, str] = {}
        for path in zoxide_paths:
            zoxide_by_name.setdefault(Path(path).name, path)

        for session_file in session_files:
            session_name = session_file.stem
            open_session = open_sessions.get(session_name)
            stats = open_session.stats if open_session is not None else None
            branch = git_branch(zoxide_by_name.get(session_name))
            entries.append(
                PickerEntry(
                    entry_type=SESSION_ENTRY,
                    session_name=session_name,
                    session_file=session_file,
                    session_path=None,
                    stats=stats,
                    display_label=self.format_entry_label(
                        SESSION_ENTRY, session_name, None, stats, branch
                    ),
                    selection_key=f"{SESSION_ENTRY}:{session_file}",
                )
            )

        for path in zoxide_paths:
            session_name = Path(path).name
            if session_name in session_names:
                continue
            open_session = open_sessions.get(session_name)
            stats = open_session.stats if open_session is not None else None
            session_file = self.context.session_dir / f"{session_name}.kitty-session"
            branch = git_branch(path)
            entries.append(
                PickerEntry(
                    entry_type=PATH_ENTRY,
                    session_name=session_name,
                    session_file=session_file,
                    session_path=path,
                    stats=stats,
                    display_label=self.format_entry_label(
                        PATH_ENTRY, session_name, path, stats, branch
                    ),
                    selection_key=f"{PATH_ENTRY}:{path}",
                )
            )

        return self.sort_entries(entries)

    def run(self) -> int:
        zoxide_output = self.run_zoxide()
        if zoxide_output is None:
            return 1

        zoxide_paths = [path for path in zoxide_output.splitlines() if path]
        zoxide_by_name: dict[str, str] = {}
        for path in zoxide_paths:
            zoxide_by_name.setdefault(Path(path).name, path)

        try:
            self.context.session_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            emit(
                f"kitty-zoxide-sessions: failed to create session directory ({exc})",
                stderr=True,
            )
            return 1

        session_files = list_session_files(self.context.session_dir)
        known_session_names = {session_file.stem for session_file in session_files}
        known_session_names.update(Path(path).name for path in zoxide_paths)
        open_sessions = self.list_open_sessions(known_session_names)
        entries = self.build_entries(session_files, zoxide_paths, open_sessions)

        candidates = "\n".join(
            f"{entry.display_label}\t{entry.selection_key}" for entry in entries
        )
        if not candidates:
            emit("kitty-zoxide-sessions: no sessions found", stderr=True)
            return 1

        selection_key_pressed, selection, selection_status = select_structured_item(
            candidates, "session > ", ansi=self.context.ansi
        )
        if selection_status != 0:
            return selection_status

        if not selection:
            emit("No session selected", stderr=True)
            emit(self.context.parser.format_help(), stderr=True)
            return 1

        _, _, selection_key = selection.rpartition("\t")
        entry = next(
            (entry for entry in entries if entry.selection_key == selection_key), None
        )
        if entry is None:
            emit("kitty-zoxide-sessions: selection could not be resolved", stderr=True)
            return 1

        if selection_key_pressed == "ctrl-x":
            open_session = open_sessions.get(entry.session_name)
            if open_session is None:
                emit(
                    "kitty-zoxide-sessions: only open sessions can be closed",
                    stderr=True,
                )
                return 1
            if not self.confirm_close(
                entry.session_name, is_active=open_session.stats.is_active
            ):
                emit("Close cancelled", stderr=True)
                return 1
            return self.close_open_session(entry.session_name, open_session)

        resolved_session_file: Path | int
        if entry.entry_type == SESSION_ENTRY:
            resolved_session_file = entry.session_file
            session_name = resolved_session_file.stem
            session_path_from_zoxide = zoxide_by_name.get(session_name)
        else:
            session_name = entry.session_name
            session_path_from_zoxide = entry.session_path
            resolved_session_file = entry.session_file

        if session_path_from_zoxide is not None:
            resolved_session_file = self.ensure_session_file(
                self.context.session_dir,
                session_name,
                session_path_from_zoxide,
                self.context.debug,
                self.context.template_path,
            )

        log(
            f"Variables set: session={session_name} path={session_path_from_zoxide or 'n/a'}",
            self.context.debug,
        )

        if isinstance(resolved_session_file, int):
            return resolved_session_file

        log(
            f"Opening:{resolved_session_file} editing={'yes' if self.editing else ''}",
            self.context.debug,
        )

        return self.handle_session(resolved_session_file)


class EditSession(SessionSelection):
    def __init__(self, context: AppContext) -> None:
        super().__init__(context, editing=True)

    def launch_editor(self, session_file: Path) -> int:
        default_editor = "nvim"
        editor = os.environ.get("EDITOR", default_editor)
        editor_parts = shlex.split(editor) if editor else [default_editor]
        editor_parts.append(str(session_file))
        try:
            result = subprocess.run(editor_parts)
            return result.returncode
        except FileNotFoundError:
            emit(
                f"kitty-zoxide-sessions: editor '{editor_parts[0]}' not found",
                stderr=True,
            )
            return 1

    def handle_session(self, session_file: Path) -> int:
        return self.launch_editor(session_file)


class LaunchSession(SessionSelection):
    def __init__(self, context: AppContext) -> None:
        super().__init__(context, editing=False)

    def handle_session(self, session_file: Path) -> int:
        result = run_kitten(
            "action", "goto_session", str(session_file), to=self.context.remote_to
        )
        if result is None:
            return 1

        return result.returncode


def main(argv: list[str]) -> int:
    session_dir = resolve_session_dir()
    setup_logging(session_dir)

    parser = build_parser()
    parsed = parse_args(parser, argv)
    if isinstance(parsed, int):
        return parsed

    editing = parsed.edit
    deleting = parsed.delete
    delete_all = parsed.delete_all
    debug = parsed.debug
    auto_close = parsed.auto_close
    ansi = parsed.ansi
    template_path = Path(parsed.template).expanduser() if parsed.template else None
    target = parsed.target
    remote_to = resolve_main_listen_on(parsed.main_listen_on)
    launcher_window_id = os.environ.get("KITTY_WINDOW_ID")

    if editing and (deleting or delete_all):
        emit(
            "kitty-zoxide-sessions: cannot use --edit with delete options", stderr=True
        )
        return 1

    if deleting and delete_all:
        emit(
            "kitty-zoxide-sessions: cannot use --delete with --delete-all", stderr=True
        )
        return 1

    if auto_close:
        atexit.register(close_launcher_window, launcher_window_id)

    context = AppContext(
        session_dir=session_dir,
        parser=parser,
        debug=debug,
        ansi=ansi,
        template_path=template_path,
        launcher_window_id=launcher_window_id,
        target=target,
        remote_to=remote_to,
    )

    if delete_all:
        op = DeleteAllSessions(context)
    elif deleting:
        op = DeleteSession(context)
    elif editing:
        op = EditSession(context)
    else:
        op = LaunchSession(context)

    return op.run()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
