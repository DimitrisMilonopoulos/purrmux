#!/usr/bin/env python3
"""Drive the agents running in kitty from outside them.

The pickers in this directory are the same verbs behind a keypress: the
overview focuses a window, the phone TUI types into one, its ``n`` screen
starts one. This is those verbs with no UI in front of them, so a script — or
an agent, through ``agent_mcp.py`` — can do the same things.

Everything goes through ``agents.py``, which is also what the sidebar, the
overview and the ignis deck read, so nothing here can disagree with what you
are looking at.

One rule: **agent windows only**. A window that never reported a status, never
named an agent and was not opened by this tool is somebody's shell or editor,
and every command that names a window refuses it. Spawning is the exception
that proves it — a window it opens is ours from birth, because ``spawn`` stamps
it (see ``agents.SPAWN_VAR``).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import agents
from agents import (
    Agent,
    collect_agents,
    discover_control_address,
    find_window,
    is_agent_window,
    kitty_state,
    read_lines,
    use_control_address,
    worktrees,
)

# How long `wait` hangs on by default. It is short on purpose: the caller is
# usually an agent whose tool call is blocked for the whole of it, and polling
# twice beats one call that looks hung for ten minutes.
DEFAULT_WAIT_SECONDS = 120
DEFAULT_POLL_SECONDS = 2.0

# The statuses `wait` stops on unless told otherwise — the ones that mean the
# agent has stopped doing and started waiting.
DEFAULT_WAIT_FOR = ("blocked", "done", "error")


def fail(message: str) -> int:
    print(f"kitty-agent: {message}", file=sys.stderr)
    return 1


# --- shaping output ---------------------------------------------------------


def as_dict(agent: Agent) -> dict[str, object]:
    return {
        "window_id": agent.window_id,
        "agent": agent.agent,
        "session": agent.session,
        "status": agent.status,
        "attention": agent.has_attention,
        "title": agent.title,
        "cwd": agent.cwd,
        "branch": agent.branch,
        "age": agent.age,
    }


def emit(payload: dict[str, object], human: str, *, as_json: bool) -> None:
    print(json.dumps(payload, indent=2) if as_json else human)


def agent_line(agent: Agent) -> str:
    """One agent, in the overview's columns minus its colours."""
    marker = "!" if agent.has_attention else " "
    where = " · ".join(filter(None, [agent.session, agent.branch]))
    return (
        f"{marker} {agent.window_id:>4}  {agent.dot} {agent.status:<8}"
        f" {agent.agent:<9} {agent.age:>4}  {agent.title}"
        + (f"  ({where})" if where else "")
    )


# --- the guard --------------------------------------------------------------


def self_window_id() -> int | None:
    """The window this is running in, when it is running in one at all."""
    value = os.environ.get("KITTY_WINDOW_ID", "")
    return int(value) if value.isdigit() else None


def agent_window(window_id: int) -> dict | int:
    """The window with this id, if it is an agent's. An exit code if not."""
    window = find_window(kitty_state(), window_id)
    if window is None:
        return fail(f"no window {window_id}")
    if not is_agent_window(window):
        return fail(
            f"window {window_id} is not an agent window — "
            "this tool only drives windows running an agent"
        )
    # An agent typing into its own window is a loop, and closing it is worse.
    if window_id == self_window_id():
        return fail(f"window {window_id} is the one this is running in")
    return window


def agent_by_id(window_id: int) -> Agent | None:
    return next(
        (a for a in collect_agents(kitty_state()) if a.window_id == window_id),
        None,
    )


# --- worktrees --------------------------------------------------------------


def git(*args: str) -> list[str]:
    return read_lines("git", *args)


def repo_root(directory: str) -> str:
    """The main worktree of the repo ``directory`` is in, or ""."""
    trees = worktrees(directory)
    return trees[0][0] if trees else ""


def worktree_home(repo: str) -> Path:
    """Where this repo's worktrees already live, or where they should.

    Read off the repo rather than configured, because a repo that already has
    worktrees has already answered the question — and answered it in whatever
    shape its owner likes, which is rarely ``<repo>-worktrees``.
    """
    root = Path(repo)
    parents = Counter(
        Path(path).parent
        for path, _ in worktrees(repo)[1:]
        # Worktrees *inside* the repo are somebody's scratch space — Claude Code
        # keeps dozens under .claude/worktrees — and outnumbering the real ones
        # is not the same as being them.
        if not Path(path).is_relative_to(root)
    )
    if parents:
        return parents.most_common(1)[0][0]
    return root.parent / f"{root.name}-worktrees"


def branch_prefix(repo: str) -> str:
    """The ``feature/`` in ``feature/dark-mode``, if the repo works that way."""
    head = git("-C", repo, "rev-parse", "--abbrev-ref", "HEAD")
    current = head[0] if head else ""
    prefix, sep, _ = current.partition("/")
    return f"{prefix}/" if sep else ""


def branch_exists(repo: str, branch: str) -> bool:
    return bool(
        git("-C", repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    )


def ensure_worktree(repo: str, name: str, branch: str | None) -> tuple[str, str] | int:
    """``(path, branch)`` for a worktree called ``name``, made if it isn't there."""
    for path, existing in worktrees(repo):
        if Path(path).name == name:
            return path, existing

    path = worktree_home(repo) / name
    if path.exists():
        return fail(f"{path} already exists and is not a worktree of {repo}")

    branch = branch or f"{branch_prefix(repo)}{name}"
    add = ["git", "-C", repo, "worktree", "add", str(path)]
    add += [branch] if branch_exists(repo, branch) else ["-b", branch]

    result = subprocess.run(
        add, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if result.returncode != 0:
        return fail(result.stderr.strip() or f"failed to create worktree {path}")
    return str(path), branch


# --- commands ---------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    found = collect_agents(kitty_state(), attention_only=args.attention)
    if args.session:
        found = [a for a in found if a.session == args.session]
    if args.status:
        found = [a for a in found if a.status == args.status]
    if args.mine:
        found = [a for a in found if a.window_id in spawned_by(os.environ.get("KITTY_WINDOW_ID"))]

    if args.json:
        print(json.dumps({"agents": [as_dict(a) for a in found]}, indent=2))
        return 0
    if not found:
        print("No agents running")
        return 0
    print("\n".join(agent_line(agent) for agent in found))
    return 0


def spawned_by(parent: str | None) -> set[int]:
    """Window ids stamped with this parent, for ``list --mine``."""
    if not parent:
        return set()
    state = kitty_state()
    ids: set[int] = set()
    for agent in collect_agents(state):
        window = find_window(state, agent.window_id) or {}
        user_vars = window.get("user_vars") or {}
        if str(user_vars.get(agents.SPAWN_VAR)) == str(parent):
            ids.add(agent.window_id)
    return ids


def cmd_spawn(args: argparse.Namespace) -> int:
    cwd = str(Path(args.cwd or os.getcwd()).expanduser().resolve())
    branch = ""
    created = False

    if args.worktree:
        repo = repo_root(str(Path(args.repo or cwd).expanduser()))
        if not repo:
            return fail(f"{args.repo or cwd} is not a git repository")
        before = {Path(path).name for path, _ in worktrees(repo)}
        resolved = ensure_worktree(repo, args.worktree, args.branch)
        if isinstance(resolved, int):
            return resolved
        cwd, branch = resolved
        created = args.worktree not in before

    session = args.session or Path(cwd).name
    parent = os.environ.get("KITTY_WINDOW_ID")
    window_id = agents.spawn(
        args.agent,
        cwd=cwd,
        session=session,
        title=args.title,
        prompt=args.prompt,
        target=args.target,
        focus=args.focus,
        parent_window_id=int(parent) if parent and parent.isdigit() else None,
    )
    if window_id is None:
        return fail(f"failed to start {args.agent}")

    emit(
        {
            "window_id": window_id,
            "agent": args.agent,
            "session": session,
            "cwd": cwd,
            "branch": branch or agents.git_branch(cwd),
            "created_worktree": created,
        },
        f"started {args.agent} in window {window_id} · {session} · {cwd}",
        as_json=args.json,
    )
    return 0


def cmd_screen(args: argparse.Namespace) -> int:
    window = agent_window(args.window_id)
    if isinstance(window, int):
        return window

    text = agents.screen_text(
        args.window_id,
        ansi=args.ansi,
        extent="screen" if args.screen_only else "all",
    )
    if text is None:
        return fail(f"could not read window {args.window_id}")
    # kitty pads the screen out to its height; the blank rows are never the
    # part you wanted.
    lines = text.rstrip("\n").splitlines()
    if args.lines:
        lines = lines[-args.lines :]

    if args.json:
        print(json.dumps({"window_id": args.window_id, "screen": "\n".join(lines)}, indent=2))
        return 0
    print("\n".join(lines))
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    window = agent_window(args.window_id)
    if isinstance(window, int):
        return window

    code = agents.send_text(args.window_id, args.text)
    if code == 0 and args.submit:
        code = agents.send_key(args.window_id, "enter")
    if code == 0:
        emit(
            {"window_id": args.window_id, "sent": args.text},
            f"sent to window {args.window_id}",
            as_json=args.json,
        )
    return code


def cmd_focus(args: argparse.Namespace) -> int:
    window = agent_window(args.window_id)
    if isinstance(window, int):
        return window
    return agents.focus_window(args.window_id)


def cmd_close(args: argparse.Namespace) -> int:
    window = agent_window(args.window_id)
    if isinstance(window, int):
        return window
    return agents.close_window(args.window_id)


def cmd_wait(args: argparse.Namespace) -> int:
    window = agent_window(args.window_id)
    if isinstance(window, int):
        return window

    wanted = {status.strip() for status in args.until.split(",") if status.strip()}
    deadline = time.monotonic() + args.timeout
    agent = agent_by_id(args.window_id)

    while True:
        agent = agent_by_id(args.window_id)
        if agent is None:
            emit(
                {"window_id": args.window_id, "status": "gone", "timed_out": False},
                f"window {args.window_id} is gone",
                as_json=args.json,
            )
            return 3
        if agent.status in wanted:
            emit(
                {**as_dict(agent), "timed_out": False},
                agent_line(agent),
                as_json=args.json,
            )
            return 0
        if time.monotonic() >= deadline:
            emit(
                {**as_dict(agent), "timed_out": True},
                f"still {agent.status} after {args.timeout}s: {agent_line(agent)}",
                as_json=args.json,
            )
            return 2
        time.sleep(args.interval)


def cmd_worktrees(args: argparse.Namespace) -> int:
    directory = str(Path(args.repo or os.getcwd()).expanduser())
    trees = worktrees(directory)
    if not trees:
        return fail(f"{directory} is not a git repository")

    if args.json:
        print(json.dumps({"worktrees": [{"path": p, "branch": b} for p, b in trees]}, indent=2))
        return 0
    for path, branch in trees:
        print(f"{path}\t{branch}")
    return 0


# --- wiring -----------------------------------------------------------------


def window_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("window_id", type=int, help="Window id, from `list`")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kitty-agent",
        description="Spawn and drive the agents running in kitty.",
    )
    parser.add_argument(
        "--to",
        metavar="ADDRESS",
        help=(
            "Remote-control socket of the kitty instance to drive (e.g. "
            "'unix:@kitty-1234'), or 'auto' to find one. Needed wherever the "
            "ambient socket isn't the instance you mean — over ssh, say."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    subparsers = parser.add_subparsers(dest="command", required=True)

    listing = subparsers.add_parser("list", help="Every agent kitty knows about")
    listing.add_argument("--session", help="Only this session")
    listing.add_argument("--status", help="Only this status")
    listing.add_argument("--attention", action="store_true", help="Only ones waiting for you")
    listing.add_argument("--mine", action="store_true", help="Only ones this window spawned")
    listing.set_defaults(func=cmd_list)

    spawn = subparsers.add_parser("spawn", help="Start an agent in a new tab or window")
    spawn.add_argument("--agent", default="claude", help="claude, codex or opencode")
    spawn.add_argument("--prompt", help="What to give it to do, submitted on start")
    spawn.add_argument("--cwd", help="Where to run it (default: here)")
    spawn.add_argument("--session", help="Session to group it under (default: the folder's name)")
    spawn.add_argument("--repo", help="Repo to take the worktree from (default: --cwd)")
    spawn.add_argument("--worktree", help="Worktree to use, created if it isn't there")
    spawn.add_argument("--branch", help="Branch for a new worktree (default: the repo's prefix + its name)")
    spawn.add_argument(
        "--title",
        help=(
            "Pin the tab title. Left alone by default, so the agent's own title "
            "— which is where Claude Code writes what it is doing — reaches the "
            "sidebar and the overview"
        ),
    )
    spawn.add_argument(
        "--focus",
        action="store_true",
        help="Switch to the new window instead of leaving you where you are",
    )
    spawn.add_argument(
        "--target",
        default="auto",
        choices=("auto", "tab", "window"),
        help="auto puts it beside its session, or in a window of its own",
    )
    spawn.set_defaults(func=cmd_spawn)

    screen = subparsers.add_parser("screen", help="What an agent's screen says right now")
    window_arg(screen)
    screen.add_argument(
        "--lines", type=int, default=60, help="Only the last N lines. Default 60"
    )
    screen.add_argument(
        "--screen-only",
        action="store_true",
        help=(
            "Just the visible rows. The default reads the scrollback too, "
            "because a finished agent has already collapsed what it said"
        ),
    )
    screen.add_argument("--ansi", action="store_true", help="Keep the colours")
    screen.set_defaults(func=cmd_screen)

    send = subparsers.add_parser("send", help="Type into an agent")
    window_arg(send)
    send.add_argument("text", help="What to type")
    send.add_argument(
        "--no-submit",
        dest="submit",
        action="store_false",
        help="Leave it in the prompt instead of pressing enter",
    )
    send.set_defaults(func=cmd_send, submit=True)

    focus = subparsers.add_parser("focus", help="Bring an agent's window to the front")
    window_arg(focus)
    focus.set_defaults(func=cmd_focus)

    close = subparsers.add_parser("close", help="Close an agent's window")
    window_arg(close)
    close.set_defaults(func=cmd_close)

    wait = subparsers.add_parser("wait", help="Block until an agent stops working")
    window_arg(wait)
    wait.add_argument("--until", default=",".join(DEFAULT_WAIT_FOR), help="Statuses to stop on")
    wait.add_argument("--timeout", type=float, default=DEFAULT_WAIT_SECONDS)
    wait.add_argument("--interval", type=float, default=DEFAULT_POLL_SECONDS)
    wait.set_defaults(func=cmd_wait)

    trees = subparsers.add_parser("worktrees", help="Every worktree of a repo")
    trees.add_argument("--repo", help="Repo to look at (default: here)")
    trees.set_defaults(func=cmd_worktrees)

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv[1:])

    if args.to:
        address = discover_control_address() if args.to == "auto" else args.to
        if not address:
            return fail("could not find a running kitty")
        use_control_address(address)
        os.environ["KITTY_LISTEN_ON"] = address

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
