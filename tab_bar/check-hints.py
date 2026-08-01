#!/usr/bin/env python3
"""Check that the tab bar's mode hints match keybinds.conf.

The hints in tab_bar/config.py are written by hand, because grouping keys into
readable clusters ("hjkl focus" rather than four entries) is a judgement call a
parser would make badly. The cost is drift: the tab bar once advertised `w
picker` under tab mode while `w` was only ever bound in pane mode.

This turns that drift into a failure. Run it after editing either file:

    python3 tab_bar/check-hints.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYBINDS = ROOT / "keybinds.conf"
CONFIG = ROOT / "tab_bar" / "config.py"

# Every map option this config uses takes a value, so a flag and its argument
# are always two tokens and the key is whatever follows them.
VALUED_FLAGS = {
    "--mode",
    "--new-mode",
    "--on-unknown",
    "--on-action",
    "--timeout",
    "--when-focus-on",
}

# Hint fragments that name something other than a literal key.
LITERAL_EXPANSIONS = {"1-9": [str(n) for n in range(1, 10)], "^g": ["ctrl+g"]}
WILDCARDS = {"*"}


def load_config_module():
    spec = importlib.util.spec_from_file_location("tab_bar_config", CONFIG)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_bindings() -> dict[str, set[str]]:
    """Map every keyboard mode to the set of keys bound in it."""
    bound: dict[str, set[str]] = {}

    for line in KEYBINDS.read_text(encoding="utf-8").splitlines():
        tokens = line.strip().split()
        if not tokens or tokens[0] != "map":
            continue

        mode = ""
        index = 1
        while index < len(tokens) and tokens[index].startswith("--"):
            if tokens[index] in VALUED_FLAGS:
                if tokens[index] == "--mode":
                    mode = tokens[index + 1]
                index += 2
            else:
                index += 1

        if index >= len(tokens):
            continue

        bound.setdefault(mode, set()).add(tokens[index])

    return bound


def expand(fragment: str) -> list[str]:
    """Turn a hint fragment such as "hjkl" or "1-9" into the keys it names."""
    fragment = fragment.strip()
    if fragment in WILDCARDS:
        return []
    if fragment in LITERAL_EXPANSIONS:
        return LITERAL_EXPANSIONS[fragment]
    # Hints show "HJKL" because that is what you type, but keybinds.conf has to
    # spell it `shift+h` for kitty to see a distinct trigger at all.
    return [f"shift+{c.lower()}" if c.isupper() else c for c in fragment]


def main() -> int:
    config = load_config_module()
    bound = parse_bindings()
    problems: list[str] = []

    for mode, hints in config.MODE_HINTS.items():
        keys = bound.get(mode)
        if keys is None:
            problems.append(f"{mode}: hinted, but keybinds.conf binds nothing in it")
            continue

        hinted: set[str] = set()
        for fragment, label in (pair for group in hints for pair in group[1]):
            for key in expand(fragment):
                hinted.add(key)
                if key not in keys:
                    problems.append(
                        f"{mode}: hint {fragment.strip()!r} ({label}) names {key!r},"
                        " which is not bound in that mode"
                    )

        for key in sorted(keys - hinted):
            print(f"note: {mode} binds {key!r} but no hint mentions it")

    if problems:
        print()
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    print(f"\nhints match keybinds.conf across {len(config.MODE_HINTS)} modes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
