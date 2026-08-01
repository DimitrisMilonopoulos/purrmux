"""Where a kitty session lives on disk.

The session picker writes one file per session (session-management/kitty-zoxide-sessions.py)
and records the directory the session was opened in as a ``cd`` line in it. That
directory is the session's root and it stays put, which is what the footer wants
a branch for — unlike the cwd of whatever window happens to be focused, which
moves every time you cd and can sit in a different repo entirely.
"""

import os
from pathlib import Path

# session name -> (mtime of its file, the root it names). The file only changes
# when the session is created or edited, so its mtime is enough to cache on.
_root_cache: dict[str, tuple[int, Path | None]] = {}


def get_session_dir() -> Path:
    """Where the picker keeps its session files — the same rule it uses."""
    data_home = os.environ.get("XDG_DATA_HOME")
    base_dir = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base_dir / "kitty-sessions"


def parse_session_root(path: Path) -> Path | None:
    """The directory a session file opens in, from its first ``cd``."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    for line in text.splitlines():
        directive, _, argument = line.strip().partition(" ")
        argument = argument.strip()
        if directive == "cd" and argument:
            return Path(os.path.expanduser(argument))

    return None


def get_session_root(name: str) -> Path | None:
    """The root directory of the session called ``name``, if it has a file.

    Sessions started any other way — the startup session, a kitty --session on
    the command line — have no file here, and callers fall back to a cwd.
    """
    if not name:
        return None

    path = get_session_dir() / f"{name}.kitty-session"
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return None

    cached = _root_cache.get(name)
    if cached is not None and cached[0] == mtime_ns:
        return cached[1]

    root = parse_session_root(path)
    _root_cache[name] = (mtime_ns, root)
    return root
