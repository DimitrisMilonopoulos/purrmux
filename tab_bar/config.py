import re
from pathlib import Path


# "chip"    -> powerline chips with filled icon blocks and bodies (default)
# "minimal" -> flat text + colored icons, sections divided by MINIMAL_SEPARATOR
TAB_BAR_STYLE = "chip"
MINIMAL_SEPARATOR = "·"

# Render tab bar text smaller than the rest of the UI via kitty's text sizing
# protocol (kitty >= 0.40). None = full size (default). A (numerator,
# denominator) tuple draws glyphs at that fraction of the cell, e.g. (2, 3).
# Cell widths are unchanged (1 char still = 1 column), so tighter fractions
# look more loosely tracked. Only the "minimal" style honors this; powerline
# "chip" borders can't scale. Set back to None to fully revert.
TAB_BAR_TEXT_SCALE: tuple[int, int] | None = None

# Sidebar mode (tab_bar_edge left/right, kitty >= 0.48). Toggle it at runtime
# with tab_bar/toggle-edge.py; these only affect how the sidebar is drawn.
# VERTICAL_ACTIVE_MARKER: column drawn at the outer edge of the active tab's
# row ("" disables it). VERTICAL_SEPARATOR: full-height rule down the inner
# edge, dividing the sidebar from the panes ("" disables it, giving the column
# back to the tab titles). VERTICAL_SHOW_STATUS: the branch of the active tab —
# plus the keyboard mode and its hints — stacked at the bottom of the sidebar.
# VERTICAL_SHOW_AGENT_STATUS: agent status ("working · claude") on the spare row
# under each agent tab, when kitty gives tabs two rows each.
VERTICAL_ACTIVE_MARKER = "▎"
VERTICAL_SEPARATOR = "│"
VERTICAL_SHOW_STATUS = True
VERTICAL_SHOW_AGENT_STATUS = True

# Agents report a status into the agent_status user var from the attention hooks
# (hooks/install-attention-hooks.sh). AGENT_EXES are the processes recognised as
# agents when no hook has reported yet, so a status can still be derived.
# How the sidebar's bottom block is drawn. "minimal" is flat — a coloured icon
# and plain text — because powerline caps read as chunky pills once they are
# stacked in a narrow column; "chip" matches the tab pills instead.
VERTICAL_FOOTER_STYLE = "minimal"

# Icon colour per footer row, named after a kitty palette option so it follows
# whatever theme is loaded. The icons carry the colour and the text stays muted,
# which keeps the block readable as one unit. None for any row = muted like its
# text. The mode row uses the theme accent instead, like the active tab.
VERTICAL_FOOTER_ICON_COLORS = {
    "session": "color6",
    "branch": "color5",
    "folder": "color3",
    "attention": "color1",
}

AGENT_EXES = ("claude", "opencode", "codex")
AGENT_STATUS_DOTS = {"idle": "○"}
AGENT_STATUS_DOT = "●"

# Font size of the sidebar's secondary rows — agent status and mode hints — as a
# (numerator, denominator) fraction of the cell, via kitty's text sizing
# protocol. Column widths are unaffected. None = same size as everything else.
# The tab chips can't scale: powerline borders are drawn as glyphs.
# Tighter fractions also read as more loosely tracked, since the glyphs shrink
# but the columns don't: (9, 10) is barely there, (2, 3) is noticeably smaller.
VERTICAL_SECONDARY_TEXT_SCALE: tuple[int, int] | None = (9, 10)

ENABLE_APP_ICONS = True
SHOW_AGENT_ATTENTION = True
SHOW_RIGHT_FOLDER = False
SHOW_SEQUENCE_HINTS = False

REFRESH_TIME = 15
MAX_LENGTH_PATH = 3
MAX_LENGTH_BRANCH = 35
MAX_LENGTH_TITLE_ACTIVE = 30
MAX_LENGTH_TITLE_INACTIVE = 15


_KEYBINDS_CONF_PATH = Path(__file__).resolve().parent.parent / "keybinds.conf"
_ACTION_LABEL_ALIASES = {
    "kitty-zoxide-sessions": "sessions",
    "attention-picker": "attention",
    "lazygit": "git",
    "lazydocker": "docker",
}


def _normalize_action_token(token: str) -> str:
    stripped = token.strip().strip("\"'")
    stem = Path(stripped).name.removesuffix(".py")

    if stem in _ACTION_LABEL_ALIASES:
        return _ACTION_LABEL_ALIASES[stem]

    stem = stem.removeprefix("kitty-")
    stem = stem.removeprefix("focus-or-launch-tool-")
    return stem.replace("-", " ").replace("_", " ").strip() or "action"


def _label_from_action(action: str) -> str:
    skipped_tokens = {
        "launch",
        "combine",
        "sh",
        "-c",
        "python",
        "python3",
        "current",
    }

    for token in reversed(action.replace(":", " ").split()):
        if token.startswith("--") or token in skipped_tokens:
            continue
        return _normalize_action_token(token)

    return "action"


def _load_sequence_hints() -> list[tuple[str, str]]:
    if not _KEYBINDS_CONF_PATH.exists():
        return []

    pattern = re.compile(r"^\s*map\s+ctrl\+a>(\S+)\s+(.+?)\s*$")
    hints: list[tuple[str, str]] = []

    for line in _KEYBINDS_CONF_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        match = pattern.match(line)
        if not match:
            continue

        key, action = match.groups()
        hints.append((f"^a {key} ", _label_from_action(action)))

    return hints


DEFAULT_SEQUENCE_HINTS = [
    ("^a k ", "sessions"),
    ("^a a ", "attention"),
    ("^a b ", "btop"),
    ("^a g ", "git"),
    ("^a d ", "docker"),
]

SEQUENCE_HINTS = _load_sequence_hints() or DEFAULT_SEQUENCE_HINTS

APP_ICONS: dict[str, str] = {
    "claude": "\U000f06a9",
    "opencode": "\U000f167a",
    "nvim": "",
    "lazygit": "",
    "lazydocker": "",
}

FOLDER_ICON = " "
BRANCH_ICON = " "
MODE_ICON = "󰘳 "
ZOOM_ICON = " "
SESSION_ICON = " "
ATTENTION_ICON = "! "

MODE_LABELS = {
    "": "normal",
    "__sequence__": "leader",
    "pane": "pane",
    "tabmode": "tab",
    "scrollmode": "scroll",
    "opacitymode": "opacity",
    "locked": "locked",
    "zoom": "zoom",
}

MODE_HINTS = {
    "pane": [
        ("hjkl ", "focus"),
        ("HJKL ", "move"),
        ("v ", "vsplit"),
        ("s ", "split"),
        ("g ", "git"),
        ("d ", "docker"),
        ("x ", "close"),
        ("-= ", "height"),
        (",. ", "width"),
    ],
    "tabmode": [
        ("n ", "new"),
        ("x ", "close"),
        ("w ", "picker"),
        ("hl ", "switch"),
        ("r ", "rename"),
        ("v ", "sidebar"),
        ("1-9 ", "goto"),
    ],
    "scrollmode": [
        ("jk ", "line"),
        ("du ", "page"),
        ("gG ", "ends"),
    ],
    "opacitymode": [
        ("-= ", "opacity"),
        ("0 ", "reset"),
    ],
    "locked": [
        ("^g ", "unlock"),
        ("* ", "app keys"),
    ],
    "__sequence__": SEQUENCE_HINTS,
}
