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
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen
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


def ansi(text: str, code: str) -> Text:
    """Colour something the way the fzf list and the tab bar colour it.

    The codes live in agents.py so the two front ends can't drift apart; rich
    parses them back out.
    """
    return Text.from_ansi(agent_state.color(text, code, ansi=True))


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
    where = " · ".join(filter(None, [agent.agent, agent.session, agent.branch]))
    age = f" · {agent.age}" if agent.age else ""
    return Text.assemble(
        ansi(f"{agent.dot} {agent.status}", agent.status_color),
        " ",
        ansi(f"{where}{age}", "2;37"),
    )


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


def available_agents() -> list[str]:
    found = [name for name in AGENT_COMMANDS if shutil.which(name)]
    return found or list(AGENT_COMMANDS)


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
        self.query_one("#spawn-title", Static).update(title)
        self.query_one("#spawn-filter", Input).display = filtering
        listing = self.query_one("#spawn-list", ListView)
        await listing.clear()
        for index, (label, detail) in enumerate(choices):
            row = Text(label, no_wrap=True, overflow="ellipsis")
            if detail:
                row = Text.assemble(row, "\n   ", ansi(detail, "2;37"))
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
            [(name, "") for name in available_agents()],
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
        args += ["--hold", command]

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


def listed_id(item: ListItem) -> int | None:
    """The window a list row stands for, read back off its widget id."""
    return int(item.id.removeprefix("agent-")) if item.id else None


class AgentTui(App[None]):
    """List on the left, that agent's real screen on the right — or below."""

    CSS = """
    #header { padding: 0 1; color: $text-muted; height: 1; }
    #body { height: 1fr; }
    #agents { width: 46; height: 1fr; background: $surface; }
    #agents > ListItem { padding: 0 1; }
    #detail { width: 1fr; height: 1fr; }
    #detail-title { padding: 0 1; height: auto; border-bottom: solid $panel; }
    #screen-scroll { height: 1fr; padding: 0 1; }
    #replies { height: 3; align-horizontal: center; }
    #replies > Button { min-width: 7; margin: 0 1; }
    #reply { border: solid $panel; }

    #spawn { width: 100%; height: 100%; background: $surface; padding: 1; }
    #spawn-title { height: 1; color: $text-muted; padding: 0 1; }
    #spawn-filter { border: solid $panel; }
    #spawn-list { height: 1fr; }
    #spawn-list > ListItem { padding: 0 1; }

    /* Portrait: one thing at a time, the list until you pick something. */
    #body.narrow #agents { width: 1fr; }
    #body.narrow #detail { display: none; }
    #body.narrow.open #agents { display: none; }
    #body.narrow.open #detail { display: block; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "back", "back"),
        Binding("n", "new_agent", "new"),
        Binding("r", "refresh", "refresh"),
        Binding("x", "clear_attention", "clear !"),
        Binding("f", "focus_window", "focus"),
        Binding("i", "interrupt", "^C"),
        Binding("w", "toggle_wrap", "wrap"),
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
        self.load_agents()
        self.set_interval(REFRESH_SECONDS, self.tick)

    def on_resize(self, event: Resize) -> None:
        self.narrow = event.size.width < NARROW_COLUMNS
        self.query_one("#body").set_class(self.narrow, "narrow")
        self.apply_list_width()

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
                await listing.append(
                    ListItem(Static(row_text(agent, width)), id=f"agent-{agent.window_id}")
                )
            if found:
                listing.index = index
        else:
            for agent, item in zip(found, listing.children):
                item.query_one(Static).update(row_text(agent, width))

        if self.selected not in ids:
            self.selected = ids[0] if ids else None
        if self.selected is not None:
            self.show_title()

    def show_title(self) -> None:
        agent = self.agent_by_id(self.selected)
        if agent is not None:
            self.query_one("#detail-title", Static).update(title_text(agent))

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
