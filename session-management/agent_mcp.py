#!/usr/bin/env python3
"""The agent control surface, served to agents as MCP tools.

``agentctl.py`` is the same verbs for a person at a shell. This is them for
Claude Code, Codex and opencode, so an agent can say "this ticket wants its own
tree" and open one itself.

The protocol is hand-rolled for the same reason kitty's is in ``agents.py``:
it is four methods and a table of schemas, and the alternative is putting a
dependency resolve on the startup path of every agent session on the machine.
MCP's stdio transport is one JSON object per line — no Content-Length headers,
that is LSP — and the one thing that kills a server like this is a stray print
reaching stdout, so stdout is taken away from the rest of the process on the
first line of serve().

Tools that name a window go through agentctl's guard: agent windows only, and
never the window the caller is running in.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import agentctl
import agents
from agents import collect_agents, kitty_state

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "kitty-agents"
SERVER_VERSION = "1.0.0"

# The ceiling on wait_for_agent. The caller's tool call is blocked for the
# whole of it, so a long wait is two calls, not one that looks hung.
MAX_WAIT_SECONDS = 600

# How long a request already in flight gets to finish once stdin has closed.
SHUTDOWN_GRACE_SECONDS = 10.0

# What every window-naming tool says about itself, so the model knows the rule
# before it trips over it rather than after.
GUARD_NOTE = (
    " Refuses any window that is not running an agent, and the window the "
    "caller itself is running in."
)

STATUS_NOTE = (
    "Statuses: working (busy), blocked (wants a human or a reply), done "
    "(finished its turn), error, idle, starting (launched, first hook not in "
    "yet), running (an agent with no hooks installed)."
)

WINDOW_ARG = {
    "window_id": {
        "type": "integer",
        "description": "Window id, from list_agents.",
    }
}


def tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOLS = [
    tool(
        "spawn_agent",
        "Start a coding agent in a new kitty tab or OS window and return its "
        "window id. Optionally creates a git worktree first, so a ticket gets "
        "its own tree and branch. The new agent is a peer, not a subprocess: it "
        "runs until closed, and the caller tracks it with list_agents, "
        "read_agent_screen and wait_for_agent. Does not steal focus.",
        {
            "prompt": {
                "type": "string",
                "description": "What to give the new agent to do. Submitted on start.",
            },
            "agent": {
                "type": "string",
                "enum": ["claude", "codex", "opencode"],
                "description": "Which agent to run. Default claude.",
            },
            "cwd": {
                "type": "string",
                "description": "Where to run it. Default: the caller's directory.",
            },
            "repo": {
                "type": "string",
                "description": "Repository to take a worktree from. Default: cwd.",
            },
            "worktree": {
                "type": "string",
                "description": (
                    "Worktree to run in, created off the repo if it is not there "
                    "yet. Its name also becomes the session name."
                ),
            },
            "branch": {
                "type": "string",
                "description": (
                    "Branch for a newly created worktree. Default: the repo's own "
                    "branch-name prefix plus the worktree name."
                ),
            },
            "session": {
                "type": "string",
                "description": (
                    "Session to group the new tab under. Agents in one session "
                    "share an OS window. Default: the directory's name."
                ),
            },
            "target": {
                "type": "string",
                "enum": ["auto", "tab", "window"],
                "description": (
                    "auto puts it beside its session if one is open, else in an "
                    "OS window of its own."
                ),
            },
        },
        ["prompt"],
    ),
    tool(
        "list_agents",
        "Every agent running in kitty, the ones waiting on a human first. "
        + STATUS_NOTE,
        {
            "session": {"type": "string", "description": "Only this session."},
            "status": {"type": "string", "description": "Only this status."},
            "attention_only": {
                "type": "boolean",
                "description": "Only agents waiting on a human right now.",
            },
            "mine_only": {
                "type": "boolean",
                "description": "Only agents this caller spawned.",
            },
        },
        [],
    ),
    tool(
        "read_agent_screen",
        "The tail of what an agent's terminal has shown — its real progress, not "
        "a summary of it. Reads the scrollback as well as the visible screen, "
        "because an agent that has finished has already collapsed its "
        "transcript and the answer it gave has scrolled off." + GUARD_NOTE,
        {
            **WINDOW_ARG,
            "lines": {
                "type": "integer",
                "description": "Only the last N lines. Default 60.",
            },
            "screen_only": {
                "type": "boolean",
                "description": "Just the visible rows, without the scrollback.",
            },
        },
        ["window_id"],
    ),
    tool(
        "send_to_agent",
        "Type into a running agent and press enter — a follow-up instruction, or "
        "an answer to a permission prompt it is blocked on (those are numbered, "
        "so the text is often just \"1\")." + GUARD_NOTE,
        {
            **WINDOW_ARG,
            "text": {"type": "string", "description": "What to type."},
            "submit": {
                "type": "boolean",
                "description": "Press enter afterwards. Default true.",
            },
        },
        ["window_id", "text"],
    ),
    tool(
        "wait_for_agent",
        "Block until an agent stops working, then return its status and the tail "
        "of its screen. A timeout is a normal result carrying timed_out: true, "
        "not a failure — call again rather than treating it as an error." + GUARD_NOTE,
        {
            **WINDOW_ARG,
            "until": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Statuses to stop on. Default blocked, done, error.",
            },
            "timeout_seconds": {
                "type": "number",
                "description": (
                    f"Default {agentctl.DEFAULT_WAIT_SECONDS}, "
                    f"capped at {MAX_WAIT_SECONDS}."
                ),
            },
        },
        ["window_id"],
    ),
    tool(
        "focus_agent",
        "Bring an agent's window to the front on the user's desktop. This moves "
        "what the user is looking at, so only do it when they asked." + GUARD_NOTE,
        dict(WINDOW_ARG),
        ["window_id"],
    ),
    tool(
        "close_agent",
        "Close an agent's window, ending it." + GUARD_NOTE,
        dict(WINDOW_ARG),
        ["window_id"],
    ),
    tool(
        "list_worktrees",
        "Every git worktree of a repository, with the branch each is on.",
        {"repo": {"type": "string", "description": "Repository. Default: the caller's directory."}},
        [],
    ),
]


# --- the tools themselves ---------------------------------------------------
#
# Each one is a forward into agentctl, which owns the guard and the git. What
# they add is the shape the model reads back: window ids it can pass to the next
# call, and enough of a screen to know what happened without another round trip.


def _agent_dict(window_id: int) -> dict:
    agent = agentctl.agent_by_id(window_id)
    return agentctl.as_dict(agent) if agent is not None else {"window_id": window_id}


def _screen(window_id: int, lines: int = 60, *, screen_only: bool = False) -> str:
    """The tail of what a window has shown, scrollback included by default.

    An agent that has finished has already collapsed its transcript, so the
    answer it gave is above the visible screen by the time anything reads it.
    """
    text = agents.screen_text(
        window_id, ansi=False, extent="screen" if screen_only else "all"
    )
    if text is None:
        return ""
    return "\n".join(text.rstrip("\n").splitlines()[-lines:])


def _guard(window_id: int) -> dict:
    window = agentctl.find_window(kitty_state(), window_id)
    if window is None:
        raise ToolError(f"no window {window_id}")
    if not agentctl.is_agent_window(window):
        raise ToolError(
            f"window {window_id} is not an agent window — this tool only "
            "drives windows running an agent"
        )
    if window_id == agentctl.self_window_id():
        raise ToolError(f"window {window_id} is the one you are running in")
    return window


class ToolError(Exception):
    """A tool could not do what was asked. Reported to the model, not raised at it."""


def tool_spawn_agent(arguments: dict) -> dict:
    cwd = arguments.get("cwd") or os.getcwd()
    branch = ""
    created = False

    if arguments.get("worktree"):
        repo = agentctl.repo_root(str(Path(arguments.get("repo") or cwd).expanduser()))
        if not repo:
            raise ToolError(f"{arguments.get('repo') or cwd} is not a git repository")
        name = arguments["worktree"]
        before = {Path(path).name for path, _ in agentctl.worktrees(repo)}
        resolved = agentctl.ensure_worktree(repo, name, arguments.get("branch"))
        if isinstance(resolved, int):
            raise ToolError(f"could not prepare worktree {name}")
        cwd, branch = resolved
        created = name not in before

    cwd = str(Path(cwd).expanduser().resolve())
    session = arguments.get("session") or Path(cwd).name
    agent = arguments.get("agent") or "claude"
    parent = agentctl.self_window_id()

    window_id = agents.spawn(
        agent,
        cwd=cwd,
        session=session,
        prompt=arguments.get("prompt"),
        target=arguments.get("target") or "auto",
        parent_window_id=parent,
    )
    if window_id is None:
        raise ToolError(f"failed to start {agent}")

    return {
        "window_id": window_id,
        "agent": agent,
        "session": session,
        "cwd": cwd,
        "branch": branch or agents.git_branch(cwd),
        "created_worktree": created,
        "next": (
            "Track it with list_agents, read_agent_screen or wait_for_agent. "
            "It keeps running until close_agent."
        ),
    }


def tool_list_agents(arguments: dict) -> dict:
    found = collect_agents(
        kitty_state(), attention_only=bool(arguments.get("attention_only"))
    )
    if arguments.get("session"):
        found = [a for a in found if a.session == arguments["session"]]
    if arguments.get("status"):
        found = [a for a in found if a.status == arguments["status"]]
    if arguments.get("mine_only"):
        mine = agentctl.spawned_by(str(agentctl.self_window_id() or ""))
        found = [a for a in found if a.window_id in mine]
    return {"agents": [agentctl.as_dict(agent) for agent in found]}


def tool_read_agent_screen(arguments: dict) -> dict:
    window_id = int(arguments["window_id"])
    _guard(window_id)
    return {
        "window_id": window_id,
        "screen": _screen(
            window_id,
            int(arguments.get("lines") or 60),
            screen_only=bool(arguments.get("screen_only")),
        ),
    }


def tool_send_to_agent(arguments: dict) -> dict:
    window_id = int(arguments["window_id"])
    _guard(window_id)
    if agents.send_text(window_id, arguments["text"]) != 0:
        raise ToolError(f"could not type into window {window_id}")
    if arguments.get("submit", True):
        agents.send_key(window_id, "enter")
    return {"window_id": window_id, "sent": arguments["text"]}


def tool_wait_for_agent(arguments: dict) -> dict:
    window_id = int(arguments["window_id"])
    _guard(window_id)
    wanted = set(arguments.get("until") or agentctl.DEFAULT_WAIT_FOR)
    timeout = min(
        float(arguments.get("timeout_seconds") or agentctl.DEFAULT_WAIT_SECONDS),
        MAX_WAIT_SECONDS,
    )

    deadline = time.monotonic() + timeout
    while True:
        agent = agentctl.agent_by_id(window_id)
        if agent is None:
            return {"window_id": window_id, "status": "gone", "timed_out": False}
        if agent.status in wanted:
            return {
                **agentctl.as_dict(agent),
                "timed_out": False,
                "screen": _screen(window_id),
            }
        if time.monotonic() >= deadline:
            return {
                **agentctl.as_dict(agent),
                "timed_out": True,
                "screen": _screen(window_id),
                "next": "Still going. Call wait_for_agent again to keep waiting.",
            }
        time.sleep(agentctl.DEFAULT_POLL_SECONDS)


def tool_focus_agent(arguments: dict) -> dict:
    window_id = int(arguments["window_id"])
    _guard(window_id)
    if agents.focus_window(window_id) != 0:
        raise ToolError(f"could not focus window {window_id}")
    return {"window_id": window_id, "focused": True}


def tool_close_agent(arguments: dict) -> dict:
    window_id = int(arguments["window_id"])
    _guard(window_id)
    if agents.close_window(window_id) != 0:
        raise ToolError(f"could not close window {window_id}")
    return {"window_id": window_id, "closed": True}


def tool_list_worktrees(arguments: dict) -> dict:
    directory = str(Path(arguments.get("repo") or os.getcwd()).expanduser())
    trees = agentctl.worktrees(directory)
    if not trees:
        raise ToolError(f"{directory} is not a git repository")
    return {"worktrees": [{"path": path, "branch": branch} for path, branch in trees]}


HANDLERS = {
    "spawn_agent": tool_spawn_agent,
    "list_agents": tool_list_agents,
    "read_agent_screen": tool_read_agent_screen,
    "send_to_agent": tool_send_to_agent,
    "wait_for_agent": tool_wait_for_agent,
    "focus_agent": tool_focus_agent,
    "close_agent": tool_close_agent,
    "list_worktrees": tool_list_worktrees,
}


# --- the protocol -----------------------------------------------------------


def call_tool(name: str, arguments: dict) -> dict:
    """One tool call, as a result the model can read either way.

    A tool that fails comes back as a result with isError set, not as a JSON-RPC
    error: the protocol's errors are for malformed requests, and a model that is
    told "that window is not an agent" can pick a different one, where an
    aborted turn cannot.
    """
    handler = HANDLERS.get(name)
    if handler is None:
        return error_result(f"no tool named {name!r}")
    try:
        data = handler(arguments)
    except ToolError as exc:
        return error_result(str(exc))
    except Exception as exc:  # noqa: BLE001 — a broken tool must not take the server with it
        return error_result(f"{type(exc).__name__}: {exc}")
    return {
        "content": [{"type": "text", "text": json.dumps(data, indent=2)}],
        "structuredContent": data,
        "isError": False,
    }


def error_result(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def handle(request: dict, reply) -> None:
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    try:
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "ping":
            result = {}
        elif method == "tools/call":
            result = call_tool(params.get("name") or "", params.get("arguments") or {})
        else:
            reply(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"unknown method {method!r}"},
                }
            )
            return
    except Exception as exc:  # noqa: BLE001 — the loop outlives any one request
        reply(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"},
            }
        )
        return

    reply({"jsonrpc": "2.0", "id": request_id, "result": result})


def serve(address: str = "") -> int:
    """Read requests off stdin until it closes."""
    if address:
        agents.use_control_address(address)

    # stdout belongs to the protocol from here on. Anything in this process that
    # prints — agents.py's own diagnostics, a traceback — would otherwise land
    # between two JSON objects and take the connection down with it.
    out = sys.stdout
    sys.stdout = sys.stderr
    lock = threading.Lock()
    workers: list[threading.Thread] = []

    def reply(message: dict) -> None:
        with lock:
            out.write(json.dumps(message) + "\n")
            out.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            reply(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "parse error"},
                }
            )
            continue
        # A notification carries no id and must never be answered.
        if not isinstance(request, dict) or "id" not in request:
            continue
        # wait_for_agent blocks for minutes; nothing else should queue behind it.
        worker = threading.Thread(target=handle, args=(request, reply), daemon=True)
        workers = [thread for thread in workers if thread.is_alive()]
        workers.append(worker)
        worker.start()

    # stdin has closed, but a request already in flight has an answer owed to
    # it — and a client that piped its requests in is reading stdout still.
    # Daemon threads would be killed on the way out with the reply unwritten.
    deadline = time.monotonic() + SHUTDOWN_GRACE_SECONDS
    for thread in workers:
        thread.join(max(0.0, deadline - time.monotonic()))
    return 0


def main(argv: list[str]) -> int:
    address = ""
    if "--to" in argv:
        value = argv[argv.index("--to") + 1]
        address = agents.discover_control_address() if value == "auto" else value
    return serve(address)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
