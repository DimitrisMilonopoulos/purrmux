#!/usr/bin/env python3
"""Move the kitty tab bar between the sidebar and the horizontal bar, or hide it.

kitty 0.48 added vertical tabs (``tab_bar_edge left|right``) but there is no
remote-control command to set an option directly. ``load-config`` does accept
overrides though, and reloading re-reads both ``tab_bar_edge``
(``TabBar.apply_options``) and how many tabs are worth a bar at all
(``TabManager.tab_bar_should_be_visible``), so the edge switches and the bar
comes and goes live without restarting kitty.

Both directions pass their own overrides rather than one of them relying on
kitty.conf, so the toggle behaves the same whichever edge is configured as the
default — kitty.conf then only decides how kitty starts up (currently the
sidebar).

Because each call passes ``--ignore-overrides``, the overrides never stack up
across toggles; the flip side is that ``-o`` flags given on kitty's own command
line are dropped too (this config uses none), and that nothing carries over
between calls — so every call has to state the whole tab bar, edge and
visibility together, which is why hiding lives here rather than in a script of
its own. Toggling reloads the config, so runtime-only tweaks such as
``set_background_opacity`` reset to their configured values, exactly as any
other config reload would.

Hiding is per kitty instance rather than per OS window: every option below is
read from the global options that all of an instance's OS windows share, and
kitty has nothing per-window to reach for instead. Filtering a window's tabs
away does not stand in for it either — ``tabs_to_be_shown_in_tab_bar`` always
exempts the active tab, so no ``tab_bar_filter`` can leave a window with too
few tabs to draw. A second kitty process — the quick-access terminal, say —
keeps its own tab bar.

Usage: toggle-edge.py [toggle|sidebar|horizontal|left|right|top|bottom
                       |hide|show|toggle-hidden|status]
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

# How the bar is taken away, and put back. ``tab_bar_style=hidden`` is the
# option that names this, but it cannot come back in a single reload:
# ``Boss.load_config_file`` relayouts every tab before
# ``TabManager.apply_options`` re-reads the style, and ``resize`` skips laying
# the bar out while the *previous* ``tab_bar_hidden`` is still set — so leaving
# hidden shows the bar again without ever handing the panes their columns back,
# until something else relayouts them. ``tab_bar_min_tabs`` stays clear of that
# path: the bar is never "hidden", it just has too few tabs to be worth
# drawing, which is the same route kitty takes for a single-tab window, and it
# is read in time for that relayout. Both directions then take one reload.
#
# VISIBLE_MIN_TABS is what kitty.conf sets, restated here because
# --ignore-overrides means an override only holds while it is being passed.
HIDDEN_MIN_TABS = 99999
VISIBLE_MIN_TABS = 1

# How the state file spells "hidden", after the edge it is hidden at.
HIDDEN_TOKEN = "hidden"


def state_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    # Keyed on the pid, so a second instance (e.g. the quick-access terminal)
    # tracks its own tab bar. KITTY_LISTEN_ON would not do: its value depends
    # on how the script was started (a socket path from a shell, an inherited
    # fd from `launch --allow-remote-control`).
    return Path(runtime) / f"kitty-tab-bar-edge-{os.environ.get('KITTY_PID', 'default')}"


def format_state(edge: str, hidden: bool) -> str:
    return f"{edge} {HIDDEN_TOKEN}" if hidden else edge


def read_state() -> tuple[str, bool]:
    """The edge and visibility in effect, defaulting to how kitty.conf starts up.

    A file written before hiding existed holds the edge alone, which parses as
    a visible bar — the state it described.
    """
    try:
        tokens = state_path().read_text(encoding="utf-8").split()
    except OSError:
        tokens = []
    if not tokens:
        return SIDEBAR_EDGE, False
    return tokens[0], HIDDEN_TOKEN in tokens[1:]


def write_state(edge: str, hidden: bool) -> None:
    try:
        state_path().write_text(f"{format_state(edge, hidden)}\n", encoding="utf-8")
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


def apply(edge: str, hidden: bool) -> int:
    if edge in VERTICAL_EDGES:
        overrides = [
            "-o", f"tab_bar_edge={edge}",
            "-o", f"tab_title_max_length={SIDEBAR_CELLS}",
            "-o", f"tab_bar_align={SIDEBAR_ALIGN}",
        ]
    else:
        overrides = [
            "-o", f"tab_bar_edge={edge}",
            "-o", "tab_title_max_length=0",
            "-o", f"tab_bar_align={HORIZONTAL_ALIGN}",
        ]
    # The edge goes along even while hidden, so showing the bar again is a
    # reload of the edge that was in effect rather than a second decision.
    overrides += [
        "-o", f"tab_bar_min_tabs={HIDDEN_MIN_TABS if hidden else VISIBLE_MIN_TABS}",
    ]
    remote_control(*overrides)
    write_state(edge, hidden)
    return 0


def main(argv: list[str]) -> int:
    action = argv[0] if argv else "toggle"
    edge, hidden = read_state()

    if action == "status":
        print(format_state(edge, hidden))
        return 0

    # Hiding leaves the edge alone, so the bar comes back where it was instead
    # of asking you to pick an edge again.
    if action == "toggle-hidden":
        return apply(edge, not hidden)
    if action == "hide":
        return apply(edge, True)
    if action == "show":
        return apply(edge, False)

    # Asking for an edge asks for a bar on it, so these bring back a hidden one
    # rather than moving a bar you cannot see.
    if action == "toggle":
        return apply(HORIZONTAL_EDGE if edge in VERTICAL_EDGES else SIDEBAR_EDGE, False)
    if action == "sidebar":
        return apply(SIDEBAR_EDGE, False)
    if action == "horizontal":
        return apply(HORIZONTAL_EDGE, False)
    if action in (*VERTICAL_EDGES, "top", "bottom"):
        return apply(action, False)

    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
