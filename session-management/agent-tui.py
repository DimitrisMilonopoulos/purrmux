#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["textual>=5.0"]
# ///
"""The agent overview, laid out for the terminal in your pocket.

``agent-overview.py`` is fzf: two panes side by side, and a window wide enough
for both. This shows the same state from ``agents.py`` on a phone over ssh —
one column, three lines an agent, a screen you can read, and enough of a reply
bar to unblock something without a keyboard. Above roughly 90 columns it opens
back out into list-beside-screen.

Nothing here assumes kitty launched it. The instance's control socket is found
(or passed with ``--to``) rather than inherited, which is what lets it run from
an ssh session — and, later, from a server rendering the same app to a browser.

Run it with uv, which fetches textual on first use::

    ssh box -t .config/kitty/session-management/agent-tui.py
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agents as agent_state
from agents import Agent
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Color
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widget import Widget
from textual.widgets import Button, Footer, Input, ListItem, ListView, Static

REFRESH_SECONDS = 2.0

# Below this the list and the screen stop fitting beside each other, which is
# every phone held upright.
NARROW_COLUMNS = 90

# How wide the list is beside a screen, and how far it can be dragged.
LIST_WIDTH = 46
LIST_WIDTH_RANGE = (30, 80)

# Agents worth offering to start. The ones actually on PATH win; all three are
# offered when none are, since ssh logins don't always get the same PATH.
AGENT_COMMANDS = ("claude", "codex", "opencode")

# What the reply bar can send without a keyboard. Claude Code's prompts are
# numbered, so the numbers matter more than yes and no do. The payloads follow
# kitty's send-text escaping, not the shell's.
REPLIES = [
    ("1", "1"),
    ("2", "2"),
    ("3", "3"),
    ("⏎", r"\r"),
    ("esc", r"\e"),
    ("^C", r"\x03"),
]


# SGR colour codes, as agents.py writes them, to a slot in the 16-colour
# palette. Bold with a colour is how every terminal this config targets asks
# for the bright half, so it shifts by eight rather than thickening the font.
SGR_SLOTS = {str(30 + slot): slot for slot in range(8)}

_palette: dict[str, str] = {}


def palette() -> dict[str, str]:
    """The colours the running kitty is actually using.

    Read over the control socket rather than out of current-theme.conf, so the
    TUI follows a theme change without being told, and so it shows kitty's
    palette even on a phone whose terminal has its own ideas about #ff0000.
    """
    if not _palette:
        result = agent_state.run_kitten("get-colors")
        if result is not None and result.returncode == 0:
            for line in result.stdout.splitlines():
                key, _, value = line.partition(" ")
                value = value.strip()
                if key and value.startswith("#"):
                    _palette[key] = value
    return _palette


def hue(key: str, fallback: str) -> str:
    return palette().get(key, fallback)


def slot(index: int, fallback: str) -> str:
    return hue(f"color{index}", fallback)


def dimmed(color: str) -> str:
    """Half way to the background, which is what dim means here."""
    background = Color.parse(hue("background", "#1e1e1e"))
    return Color.parse(color).blend(background, 0.45).hex


def style_for(code: str) -> str:
    """One of agents.py's SGR codes, resolved against kitty's palette.

    agents.py stays the single place that decides a status is red; this decides
    which red, so the phone, the fzf overview and the sidebar dots agree.
    """
    parts = code.split(";")
    index = next((SGR_SLOTS[part] for part in parts if part in SGR_SLOTS), None)
    if index is None:
        return dimmed(hue("foreground", "#d0d0d0")) if "2" in parts else ""
    if "1" in parts:
        index += 8
    color = slot(index, "#d0d0d0")
    return dimmed(color) if "2" in parts else color


def ansi(text: str, code: str) -> Text:
    """Colour something the way the fzf list and the tab bar colour it."""
    return Text(text, style=style_for(code))


def purrmux_theme() -> Theme:
    """A textual theme cut from the kitty theme, so the two look like one thing."""
    background = hue("background", "#1e1e1e")
    return Theme(
        name="purrmux",
        primary=slot(12, "#7aa2f7"),
        secondary=slot(13, "#bb9af7"),
        accent=hue("active_tab_background", slot(11, "#e0af68")),
        warning=slot(11, "#e0af68"),
        error=slot(9, "#f7768e"),
        success=slot(10, "#9ece6a"),
        foreground=hue("foreground", "#d0d0d0"),
        background=background,
        surface=Color.parse(background).blend(Color.parse(slot(0, "#303030")), 0.5).hex,
        panel=slot(0, "#303030"),
        dark=Color.parse(background).brightness < 0.5,
    )


def row_text(agent: Agent, width: int) -> Text:
    """One agent: what it is doing, then the title, then the branch.

    Three short lines rather than one long one — a phone has rows to spare and
    no columns, and truncating a branch to fit is how the fzf list used to lose
    the end of every worktree name.
    """
    body = max(10, width - 4)
    marker = ansi("!", "1;33") if agent.has_attention else Text(" ")
    line = Text.assemble(
        marker,
        " ",
        ansi(f"{agent.dot} {agent.status:<8}", agent.status_color),
        " ",
        ansi(f"{agent.agent:<9}", "1;36"),
        " ",
        ansi(agent.age, "2;37"),
    )
    line.no_wrap = True
    line.overflow = "ellipsis"

    title = Text("   " + (agent.title or "—"), no_wrap=True, overflow="ellipsis")
    title.truncate(body)
    rows = [line, title]
    if agent.branch:
        branch = ansi("   " + agent.branch, "2;35")
        branch.no_wrap = True
        branch.overflow = "ellipsis"
        branch.truncate(body)
        rows.append(branch)
    return Text("\n").join(rows)


def title_text(agent: Agent) -> Text:
    # Age before branch: on 46 columns something has to go, and it should be
    # the end of a worktree name rather than how long it has been stuck.
    where = " · ".join(filter(None, [agent.agent, agent.session, agent.branch]))
    title = Text.assemble(
        ansi(f"{agent.dot} {agent.status}", agent.status_color),
        " ",
        ansi(agent.age, "2;37"),
        " ",
        ansi(where, "2;37"),
    )
    # One line, whatever the branch is called: three rows of wrapped worktree
    # name is most of a phone screen.
    title.no_wrap = True
    title.overflow = "ellipsis"
    return title


def read_lines(*command: str) -> list[str]:
    """Lines of a command's output, or nothing at all if it can't be run."""
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return result.stdout.splitlines() if result.returncode == 0 else []


def agent_program(name: str) -> list[str]:
    """How to start an agent from a process that is not a login shell.

    launch runs the program itself, with kitty's environment — and kitty was
    started by the desktop session, whose PATH is /usr/local/bin:/usr/bin. No
    ~/.local/bin, no version manager shims, so `claude` is simply not found.
    Resolving it here, where the login PATH applies, fixes the common case;
    anything still unfound goes through a login shell, which is how you would
    have started it by hand.
    """
    found = shutil.which(name)
    if found:
        return [found]
    return [os.environ.get("SHELL", "/bin/sh"), "-l", "-c", name]


def available_agents() -> list[tuple[str, str]]:
    """``(name, where it was found)``, so a surprise is visible before launch."""
    found = [(name, shutil.which(name) or "") for name in AGENT_COMMANDS]
    installed = [(name, path) for name, path in found if path]
    if not installed:
        return [(name, "via login shell") for name, _ in found]
    return [(name, short_path(path)) for name, path in installed]


def candidate_directories(running: list[Agent]) -> list[str]:
    """Where a new agent could go: what is already open, then zoxide.

    The directories with an agent in them come first because that is where the
    next one usually belongs — a sibling worktree of something you are already
    working in.
    """
    seen: dict[str, None] = {}
    for agent in running:
        if agent.cwd:
            seen.setdefault(agent.cwd, None)
    for line in read_lines("zoxide", "query", "-l"):
        if line:
            seen.setdefault(line, None)
    return list(seen)


def worktrees(directory: str) -> list[tuple[str, str]]:
    """``(path, branch)`` for every worktree of the repo at ``directory``.

    zoxide only knows the directories you have actually been in, so a worktree
    made on the machine and never visited is invisible to it. git isn't.
    """
    entries: list[tuple[str, str]] = []
    path = branch = ""
    for line in read_lines("git", "-C", directory, "worktree", "list", "--porcelain"):
        if line.startswith("worktree "):
            if path:
                entries.append((path, branch))
                branch = ""
            path = line.removeprefix("worktree ")
        elif line.startswith("branch "):
            branch = line.removeprefix("branch ").removeprefix("refs/heads/")
        elif line.startswith("detached"):
            branch = "detached"
    if path:
        entries.append((path, branch))
    return entries


def short_path(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path


def elide(text: str, width: int) -> str:
    """Trim a path from the left, since its end is the part that identifies it.

    ``…c/worktrees/dark-mode-toggle`` says what you picked;
    ``~/src/worktrees/dark-mode-tog…`` says what you were looking in.
    """
    return text if len(text) <= width else "…" + text[-(width - 1) :]


class SpawnScreen(ModalScreen[int | None]):
    """Start an agent: pick a folder, its worktree if it has several, then who.

    Three steps through one list, because a list is the only control that works
    the same under a thumb and under a keyboard.
    """

    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "cancel")]

    def __init__(self, running: list[Agent]) -> None:
        super().__init__()
        self.running = running
        self.step = "dir"
        self.directory = ""
        self.choices: list[tuple[str, str]] = []
        self.trees: list[tuple[str, str]] = []
        self.paths: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="spawn"):
            yield Static(id="spawn-title")
            yield Input(placeholder="filter · enter takes the top one", id="spawn-filter")
            yield ListView(id="spawn-list")

    async def on_mount(self) -> None:
        await self.show_directories()
        self.query_one("#spawn-filter", Input).focus()

    # --- the three steps -------------------------------------------------

    async def show(self, title: str, choices: list[tuple[str, str]], *, filtering: bool) -> None:
        self.choices = choices
        self.query_one("#spawn-title", Static).update(
            Text.assemble(title, " ", ansi("· esc cancels", "2;37"))
        )
        self.query_one("#spawn-filter", Input).display = filtering
        listing = self.query_one("#spawn-list", ListView)
        # Four columns of padding and scrollbar inside the list, and two more
        # of the modal's own on the first pass, before the list has a size.
        width = max(20, (listing.size.width - 4) if listing.size.width else self.app.size.width - 6)
        await listing.clear()
        for index, (label, detail) in enumerate(choices):
            row = Text(elide(label, width))
            if detail:
                row = Text.assemble(row, "\n   ", ansi(elide(detail, width - 3), "2;37"))
            await listing.append(ListItem(Static(row), id=f"choice-{index}"))
        if choices:
            listing.index = 0

    async def show_directories(self, needle: str = "") -> None:
        directories = candidate_directories(self.running)
        if needle:
            directories = [d for d in directories if needle.lower() in d.lower()]
        await self.show(
            "where should it run?",
            [(short_path(d), "") for d in directories[:200]],
            filtering=True,
        )
        self.paths = directories[:200]

    async def show_worktrees(self, needle: str = "") -> None:
        # A repo with dozens of worktrees is exactly the case this step exists
        # for, so it filters like the folder step — and the folder you picked
        # goes first, ahead of whatever git happens to list first.
        trees = self.trees
        if needle:
            trees = [
                (path, branch)
                for path, branch in trees
                if needle.lower() in path.lower() or needle.lower() in branch.lower()
            ]
        self.paths = [path for path, _ in trees]
        await self.show(
            f"which worktree of {Path(self.directory).name}?",
            [(short_path(path), branch) for path, branch in trees],
            filtering=True,
        )

    async def show_agents(self) -> None:
        self.paths = []
        await self.show(
            f"which agent, in {short_path(self.directory)}?",
            available_agents(),
            filtering=False,
        )

    # --- what a choice does ----------------------------------------------

    async def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        if self.step == "dir":
            await self.show_directories(event.value)
        elif self.step == "worktree":
            await self.show_worktrees(event.value)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        listing = self.query_one("#spawn-list", ListView)
        if listing.children:
            listing.index = listing.index or 0
            await self.take(listing.index or 0)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        index = listed_index(event.item)
        if index is not None:
            await self.take(index)

    async def take(self, index: int) -> None:
        if self.step == "agent":
            self.launch(self.choices[index][0])
            return
        if index >= len(self.paths):
            return
        self.directory = self.paths[index]
        if self.step == "dir":
            trees = worktrees(self.directory)
            if len(trees) > 1:
                self.step = "worktree"
                # The one you just picked belongs at the top; git lists the
                # main worktree first, which is rarely the one you meant.
                self.trees = sorted(trees, key=lambda t: t[0] != self.directory)
                filter_box = self.query_one("#spawn-filter", Input)
                with filter_box.prevent(Input.Changed):
                    filter_box.value = ""
                await self.show_worktrees()
                return
        self.step = "agent"
        await self.show_agents()
        self.query_one("#spawn-list", ListView).focus()


    def launch(self, command: str) -> None:
        """Put the agent where its session already lives, or in a window of its own.

        The session is the folder's name, which is what kitty-zoxide-sessions.py
        names sessions after — set as a user var so the sidebar, the overview
        and this list all group the new tab with its siblings.
        """
        session = Path(self.directory).name
        sibling = next((a for a in self.running if a.session == session), None)
        args = [
            "launch",
            "--type",
            "tab" if sibling else "os-window",
            "--cwd",
            self.directory,
            "--tab-title",
            command,
            "--var",
            f"kitty_zoxide_session={session}",
        ]
        if sibling:
            args += ["--match", f"id:{sibling.window_id}"]
        # --hold runs a shell once the agent exits, so quitting it leaves the
        # tab standing rather than taking the window with it.
        args += ["--hold", *agent_program(command)]

        result = agent_state.run_kitten(*args)
        window_id = None
        if result is not None and result.returncode == 0:
            with suppress(ValueError):
                window_id = int(result.stdout.strip())
        self.dismiss(window_id)

    def action_cancel(self) -> None:
        self.dismiss(None)


def listed_index(item: ListItem | None) -> int | None:
    return int(item.id.removeprefix("choice-")) if item and item.id else None


def band(widget: Widget, agent: Agent) -> None:
    """Carry an agent's status on a widget as classes, for the CSS to colour.

    Set one at a time rather than assigning ``classes``, which would take
    textual's own ``-highlight`` off the row with it.
    """
    for status in agent_state.STATUS_ORDER:
        widget.set_class(agent.status == status, f"status-{status}")
    widget.set_class(agent.has_attention, "attention")


def listed_id(item: ListItem) -> int | None:
    """The window a list row stands for, read back off its widget id."""
    return int(item.id.removeprefix("agent-")) if item.id else None


class AgentTui(App[None]):
    """List on the left, that agent's real screen on the right — or below."""

    CSS = """
    #header-bar { height: 1; }
    /* A header-height tap target rather than a button-looking button: it sits
       in a one-row bar, where textual's default chrome reads as an alarm. */
    #toggle-list {
        min-width: 3; width: 3; height: 1; border: none;
        background: $panel; color: $text-muted; text-style: none;
    }
    #toggle-list:hover { background: $accent; color: $background; }
    #header { padding: 0 1; color: $text-muted; height: 1; width: 1fr; }
    #body { height: 1fr; }
    #agents { width: 46; height: 1fr; background: $surface; }
    #agents > ListItem { padding: 0 1; }

    /* A band behind the whole row rather than a marker beside it: the sidebar
       does the same, and a band costs no columns, which is the scarce thing
       here. Attention is the loud one; the rest are barely there until you
       scan the column. */
    #agents > ListItem.status-blocked, #agents > ListItem.status-error,
    #detail-title.status-blocked, #detail-title.status-error { background: $error 5%; }
    #agents > ListItem.status-waiting, #agents > ListItem.status-working,
    #detail-title.status-waiting, #detail-title.status-working { background: $warning 5%; }
    #agents > ListItem.status-done, #detail-title.status-done { background: $primary 5%; }
    #agents > ListItem.attention { background: $error 12%; }
    /* Last, so the row you are on wins over whatever band it carries. */
    #agents > ListItem.-highlight { background: $accent 35%; }
    #detail { width: 1fr; height: 1fr; }
    #detail-title { padding: 0 1; height: 1; }
    #screen-scroll { height: 1fr; padding: 0 1; }
    #replies { height: 3; align-horizontal: center; }
    #replies > Button { min-width: 7; margin: 0 1; }
    #reply { border: none; height: 1; padding: 0 1; background: $panel; }

    #spawn { width: 100%; height: 100%; background: $surface; padding: 1; }
    #spawn-title { height: 1; color: $text-muted; padding: 0 1; }
    #spawn-filter { border: none; height: 1; padding: 0 1; background: $panel; }
    #spawn-list { height: 1fr; }
    #spawn-list > ListItem { padding: 0 1; }

    /* Wide: the list can be folded away to give a screen the whole window. */
    #body.collapsed #agents { display: none; }

    /* Portrait: one thing at a time, the list until you pick something. */
    #body.narrow #agents { width: 1fr; }
    #body.narrow #detail { display: none; }
    #body.narrow.open #agents { display: none; }
    #body.narrow.open #detail { display: block; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "back", "back"),
        Binding("n", "new_agent", "new"),
        Binding("b", "toggle_list", "list", show=False),
        Binding("r", "refresh", "refresh", show=False),
        Binding("x", "clear_attention", "clear !"),
        Binding("f", "focus_window", "focus", show=False),
        Binding("i", "interrupt", "^C"),
        Binding("w", "toggle_wrap", "wrap", show=False),
        Binding("[", "narrower", "narrower", show=False),
        Binding("]", "wider", "wider", show=False),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.agents: list[Agent] = []
        self.selected: int | None = None
        self.wrap = True
        self.narrow = False
        self.list_width = LIST_WIDTH

    def compose(self) -> ComposeResult:
        with Horizontal(id="header-bar"):
            yield Button("☰", id="toggle-list", compact=True)
            yield Static(id="header")
        with Horizontal(id="body"):
            yield ListView(id="agents")
            with Vertical(id="detail"):
                yield Static(id="detail-title")
                with VerticalScroll(id="screen-scroll"):
                    yield Static(id="screen")
                with Horizontal(id="replies"):
                    for index, (label, _) in enumerate(REPLIES):
                        yield Button(label, id=f"reply-{index}", compact=True)
                yield Input(placeholder="reply · enter sends", id="reply")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(purrmux_theme())
        self.theme = "purrmux"
        self.load_agents()
        self.set_interval(REFRESH_SECONDS, self.tick)

    def on_resize(self, event: Resize) -> None:
        self.narrow = event.size.width < NARROW_COLUMNS
        self.query_one("#body").set_class(self.narrow, "narrow")
        self.apply_list_width()
        # ctrl+p still opens it; the footer just has no room to say so when the
        # keys that matter here already fill the line.
        self.query_one(Footer).show_command_palette = not self.narrow

    def apply_list_width(self) -> None:
        """Give the list its columns back when it is sharing the screen.

        In portrait the list is the whole screen and a width would fight the
        stylesheet, so the fraction stays and the number waits its turn.
        """
        listing = self.query_one("#agents", ListView)
        listing.styles.width = "1fr" if self.narrow else self.list_width

    # --- kitty, off the ui thread -------------------------------------------
    # kitten @ round trips take long enough to stutter a refresh, so both of
    # them run in a worker and hand their results back.

    def tick(self) -> None:
        self.load_agents()
        if self.selected is not None and self.showing_detail:
            self.load_screen(self.selected)

    @work(thread=True, exclusive=True, group="agents")
    def load_agents(self) -> None:
        found = agent_state.collect_agents(agent_state.kitty_state())
        self.call_from_thread(self.show_agents, found)

    @work(thread=True, exclusive=True, group="screen")
    def load_screen(self, window_id: int) -> None:
        result = agent_state.run_kitten(
            "get-text", "--match", f"id:{window_id}", "--extent", "screen", "--ansi"
        )
        if result is None or result.returncode != 0:
            raw = "(could not read this window)"
        else:
            # kitty pads the screen out to its height; the blank rows would
            # push what is happening off the top of a short screen.
            raw = result.stdout.rstrip("\n")
        self.call_from_thread(self.show_screen, window_id, raw)

    @work(thread=True, group="send")
    def send(self, window_id: int, payload: str) -> None:
        agent_state.run_kitten("send-text", "--match", f"id:{window_id}", payload)

    # --- rendering ----------------------------------------------------------

    @property
    def showing_detail(self) -> bool:
        return not self.narrow or self.query_one("#body").has_class("open")

    async def show_agents(self, found: list[Agent]) -> None:
        self.agents = found
        counts = agent_state.status_counts(found) or "none"
        plural = "" if len(found) == 1 else "s"
        self.query_one("#header", Static).update(f"{len(found)} agent{plural} · {counts}")

        listing = self.query_one("#agents", ListView)
        width = listing.size.width or 46
        ids = [agent.window_id for agent in found]
        # Ages tick every refresh, so the rows are rewritten in place; the list
        # is only rebuilt when the agents themselves change, which is what
        # keeps the highlight from jumping under you while you read.
        if ids != [listed_id(item) for item in listing.children]:
            index = ids.index(self.selected) if self.selected in ids else 0
            await listing.clear()
            for agent in found:
                item = ListItem(Static(row_text(agent, width)), id=f"agent-{agent.window_id}")
                await listing.append(item)
                band(item, agent)
            if found:
                listing.index = index
        else:
            for agent, item in zip(found, listing.children):
                item.query_one(Static).update(row_text(agent, width))
                band(item, agent)

        if self.selected not in ids:
            self.selected = ids[0] if ids else None
        if self.selected is not None:
            self.show_title()

    def show_title(self) -> None:
        agent = self.agent_by_id(self.selected)
        if agent is not None:
            title = self.query_one("#detail-title", Static)
            title.update(title_text(agent))
            band(title, agent)

    def show_screen(self, window_id: int, raw: str) -> None:
        if window_id != self.selected:
            return
        text = Text.from_ansi(raw)
        text.no_wrap = not self.wrap
        screen = self.query_one("#screen", Static)
        scroll = self.query_one("#screen-scroll", VerticalScroll)
        at_bottom = scroll.scroll_offset.y >= scroll.max_scroll_y - 1
        screen.update(text)
        if at_bottom:
            scroll.scroll_end(animate=False)

    def agent_by_id(self, window_id: int | None) -> Agent | None:
        return next((a for a in self.agents if a.window_id == window_id), None)

    # --- what the keys and the buttons do -----------------------------------

    def open_selected(self) -> None:
        if self.selected is None:
            return
        self.query_one("#body").add_class("open")
        self.show_title()
        self.query_one("#screen", Static).update("…")
        self.load_screen(self.selected)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "agents":
            return
        if event.item is not None and (window_id := listed_id(event.item)) is not None:
            self.selected = window_id
            self.show_title()
            if self.showing_detail:
                self.load_screen(self.selected)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "agents":
            self.open_selected()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "toggle-list":
            self.action_toggle_list()
            return
        if self.selected is None or event.button.id is None:
            return
        index = int(event.button.id.removeprefix("reply-"))
        self.send(self.selected, REPLIES[index][1])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "reply" or self.selected is None:
            return
        # send-text reads python escapes, so a backslash someone typed has to
        # survive as one rather than becoming a control code.
        typed = event.value.replace("\\", r"\\")
        self.send(self.selected, typed + r"\r")
        event.input.value = ""

    def action_back(self) -> None:
        if self.focused is self.query_one("#reply", Input):
            self.query_one("#agents", ListView).focus()
        elif self.narrow and self.query_one("#body").has_class("open"):
            self.query_one("#body").remove_class("open")
            self.query_one("#agents", ListView).focus()
        else:
            self.exit()

    def action_refresh(self) -> None:
        self.tick()

    def action_clear_attention(self) -> None:
        if self.selected is not None:
            agent_state.clear_attention(self.selected)
            self.load_agents()

    def action_focus_window(self) -> None:
        if self.selected is not None:
            agent_state.run_kitten("focus-window", "--match", f"id:{self.selected}")

    def action_interrupt(self) -> None:
        if self.selected is not None:
            self.send(self.selected, r"\x03")

    def action_toggle_list(self) -> None:
        """Take the list away, or bring it back.

        Portrait has room for one of the two, so the toggle is the same gesture
        as picking an agent and going back; wider, it folds the list off to the
        side and gives the screen the whole window.
        """
        body = self.query_one("#body")
        if self.narrow:
            body.toggle_class("open")
        else:
            body.toggle_class("collapsed")
        if not body.has_class("open") and self.narrow:
            self.query_one("#agents", ListView).focus()
        elif self.selected is not None:
            self.load_screen(self.selected)

    def action_new_agent(self) -> None:
        self.push_screen(SpawnScreen(self.agents), self.spawned)

    def spawned(self, window_id: int | None) -> None:
        """Jump straight into what was just started, so you can watch it come up."""
        if window_id is None:
            return
        self.selected = window_id
        self.load_agents()
        self.open_selected()

    def action_wider(self) -> None:
        self.resize_list(4)

    def action_narrower(self) -> None:
        self.resize_list(-4)

    def resize_list(self, by: int) -> None:
        low, high = LIST_WIDTH_RANGE
        self.list_width = max(low, min(high, self.list_width + by))
        self.apply_list_width()

    def action_toggle_wrap(self) -> None:
        self.wrap = not self.wrap
        if self.selected is not None:
            self.load_screen(self.selected)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--to",
        default="",
        help="kitty control socket to drive (default: find a running instance)",
    )
    args = parser.parse_args(argv)

    address = args.to or agent_state.discover_control_address()
    if not address and not os.environ.get("KITTY_LISTEN_ON"):
        print(
            "agent-tui: no kitty instance answered. Is one running, and is "
            "allow_remote_control on?",
            file=sys.stderr,
        )
        return 1
    if address:
        agent_state.use_control_address(address)

    AgentTui().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
