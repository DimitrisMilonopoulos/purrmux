#!/usr/bin/env python3
"""Jump to an agent window, the ones needing attention first.

A flat list with a status per row; see agent-overview.py for the grouped view
with a live preview of each agent's screen.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass

from agents import (
    Agent,
    clear_attention,
    collect_agents,
    color,
    kitty_state,
    run_kitten,
)

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


@dataclass(frozen=True)
class Entry:
    label: str
    window_id: int


def entries(agents: list[Agent], *, ansi: bool) -> list[Entry]:
    result: list[Entry] = []
    for agent in agents:
        context = agent.session or agent.cwd or agent.title
        marker = color("!", "1;33", ansi=ansi) if agent.has_attention else " "
        status = color(f"{agent.dot} {agent.status:<8}", agent.status_color, ansi=ansi)
        name = color(agent.agent, "1;36", ansi=ansi)
        label = f"{marker} {status} {name}  {agent.title}  " + color(
            context, "2;37", ansi=ansi
        )
        result.append(Entry(label=label, window_id=agent.window_id))
    return result


def select_entry(items: list[Entry], *, ansi: bool) -> tuple[str, Entry | None]:
    candidates = "\n".join(f"{item.label}\t{item.window_id}" for item in items)
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
        "Enter focus  Ctrl-X clear attention",
        "--prompt",
        "agents > ",
    ]
    if ansi:
        fzf_command.insert(1, "--ansi")

    try:
        proc = subprocess.run(
            fzf_command,
            input=candidates,
            stdout=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        print("attention-picker: fzf command not found", file=sys.stderr)
        return "", None

    if proc.returncode != 0:
        return "", None

    lines = proc.stdout.splitlines()
    if len(lines) < 2:
        return "", None

    key = lines[0].strip()
    _, _, raw_window_id = lines[1].rpartition("\t")
    try:
        window_id = int(raw_window_id)
    except ValueError:
        return key, None

    entry = next((item for item in items if item.window_id == window_id), None)
    return key, entry


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Focus agent windows, the ones needing attention first.")
    parser.add_argument("--ansi", action="store_true", help="Enable ANSI formatting in fzf")
    parser.add_argument(
        "--attention-only",
        action="store_true",
        help="List only windows needing attention, not every agent",
    )
    args = parser.parse_args(argv[1:])

    state = kitty_state()
    if state is None:
        return 1

    agents = collect_agents(state, attention_only=args.attention_only)
    if not agents:
        print("No windows need attention" if args.attention_only else "No agents running")
        return 0

    key, entry = select_entry(entries(agents, ansi=args.ansi), ansi=args.ansi)
    if entry is None:
        return 0

    if key == "ctrl-x":
        return clear_attention(entry.window_id)

    result = run_kitten("focus-window", "--match", f"id:{entry.window_id}")
    if result is None:
        return 1
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv))
