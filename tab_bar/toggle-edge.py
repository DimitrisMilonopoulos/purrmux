#!/usr/bin/env python3
"""Switch the kitty tab bar between the vertical sidebar and the horizontal bar.

kitty 0.48 added vertical tabs (``tab_bar_edge left|right``) but there is no
remote-control command to set an option directly. ``load-config`` does accept
overrides though, and reloading re-reads ``tab_bar_edge``
(``TabBar.apply_options``), so the edge switches live without restarting kitty.

Both directions pass their own overrides rather than one of them relying on
kitty.conf, so the toggle behaves the same whichever edge is configured as the
default — kitty.conf then only decides how kitty starts up (currently the
sidebar).

Because each call passes ``--ignore-overrides``, the overrides never stack up
across toggles; the flip side is that ``-o`` flags given on kitty's own command
line are dropped too (this config uses none). Toggling reloads the config, so
runtime-only tweaks such as ``set_background_opacity`` reset to their
configured values, exactly as any other config reload would.

Usage: toggle-edge.py [toggle|sidebar|horizontal|left|right|top|bottom|status]
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

FD_RE = re.compile(r"fd:(\d+)")

VERTICAL_EDGES = ("left", "right")

# Which side the sidebar appears on, and how wide it is in title cells (kitty
# sizes the sidebar from tab_title_max_length; unset it defaults to ~20). Tabs
# start at the top so the status footer can have the bottom.
SIDEBAR_EDGE = "left"
SIDEBAR_CELLS = 26
SIDEBAR_ALIGN = "start"

# Where the horizontal bar goes, centred and with titles unlimited, as it was
# before the sidebar became the default.
HORIZONTAL_EDGE = "bottom"
HORIZONTAL_ALIGN = "center"


def state_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    # Keyed on the pid, so a second instance (e.g. the quick-access terminal)
    # tracks its own tab bar. KITTY_LISTEN_ON would not do: its value depends
    # on how the script was started (a socket path from a shell, an inherited
    # fd from `launch --allow-remote-control`).
    return Path(runtime) / f"kitty-tab-bar-edge-{os.environ.get('KITTY_PID', 'default')}"


def read_state() -> str:
    """The edge in effect, defaulting to how kitty.conf starts kitty up."""
    try:
        return state_path().read_text(encoding="utf-8").strip()
    except OSError:
        return SIDEBAR_EDGE


def write_state(edge: str) -> None:
    try:
        state_path().write_text(f"{edge}\n", encoding="utf-8")
    except OSError as err:
        print(f"warning: could not save state: {err}", file=sys.stderr)


def kitten_pass_fds() -> tuple[int, ...]:
    """The control socket `launch --allow-remote-control` hands us as an fd.

    subprocess closes descriptors above stderr by default, which would leave
    `kitten @ --to fd:N` talking to nothing.
    """
    match = FD_RE.search(os.environ.get("KITTY_LISTEN_ON", ""))
    if match is None:
        return ()
    return (int(match.group(1)),)


def remote_control(*args: str) -> None:
    kitten = shutil.which("kitten")
    cmd = [kitten, "@"] if kitten else ["kitty", "@"]

    listen_on = os.environ.get("KITTY_LISTEN_ON")
    if listen_on:
        cmd += ["--to", listen_on]

    subprocess.run(
        [*cmd, "load-config", "--ignore-overrides", *args],
        check=True,
        pass_fds=kitten_pass_fds(),
    )


def apply(edge: str) -> None:
    if edge in VERTICAL_EDGES:
        remote_control(
            "-o", f"tab_bar_edge={edge}",
            "-o", f"tab_title_max_length={SIDEBAR_CELLS}",
            "-o", f"tab_bar_align={SIDEBAR_ALIGN}",
        )
    else:
        remote_control(
            "-o", f"tab_bar_edge={edge}",
            "-o", "tab_title_max_length=0",
            "-o", f"tab_bar_align={HORIZONTAL_ALIGN}",
        )
    write_state(edge)


def main(argv: list[str]) -> int:
    action = argv[0] if argv else "toggle"
    current = read_state()

    if action == "status":
        print(current)
        return 0
    if action == "toggle":
        target = HORIZONTAL_EDGE if current in VERTICAL_EDGES else SIDEBAR_EDGE
    elif action == "sidebar":
        target = SIDEBAR_EDGE
    elif action == "horizontal":
        target = HORIZONTAL_EDGE
    elif action in (*VERTICAL_EDGES, "top", "bottom"):
        target = action
    else:
        print(__doc__, file=sys.stderr)
        return 2

    apply(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
