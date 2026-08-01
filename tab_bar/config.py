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

# How a mode's keys are drawn under its name in the footer. See MODE_HINTS.
#   "keys"   grouped, keys only — `modes  p t s o a l`. The leader fits in two
#            rows; reads as a reminder once the letters are familiar.
#   "labels" every key with its own label, two to a row — `p pane   t tab`.
#            Roughly twice the rows, but it teaches rather than reminds.
MODE_HINT_STYLE = "keys"

# Drawn in the mode row when no keyboard mode is active, so the sidebar always
# says how to reach everything else. "" leaves the row out at idle. The row
# belongs to the footer, so VERTICAL_SHOW_STATUS = False hides it too.
LEADER_HINT = "^g"

# Also list what the leader offers while idle, in the horizontal bar's left
# section. The sidebar has no room for it — it shows LEADER_HINT instead, and
# the full list once you press the leader.
SHOW_LEADER_HINTS = False

REFRESH_TIME = 15
MAX_LENGTH_PATH = 3
MAX_LENGTH_BRANCH = 35
MAX_LENGTH_TITLE_ACTIVE = 30
MAX_LENGTH_TITLE_INACTIVE = 15


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

# Mode names come from keybinds.conf (`--new-mode <name>`); the labels are what
# the tab bar shows. "zoom" is synthetic — see modes.py.
MODE_LABELS = {
    "": "normal",
    "leader": "leader",
    "pane": "pane",
    "tabmode": "tab",
    "scrollmode": "scroll",
    "sessionmode": "session",
    "appearancemode": "appearance",
    "locked": "locked",
    "zoom": "zoom",
}

# What each mode offers, grouped, shown under the mode name. These duplicate
# keybinds.conf by hand because the grouping is a judgement call a parser would
# make badly — "hjkl focus" reads better than four separate entries — so the
# two files have to be updated together. tab_bar/check-hints.py fails if a hint
# names a key the conf does not bind.
#
# One structure feeds both hint styles: MODE_HINT_STYLE "keys" draws the group
# name and its keys, "labels" ignores the grouping and draws every pair.
MODE_HINTS: dict[str, list[tuple[str, list[tuple[str, str]]]]] = {
    "leader": [
        ("modes", [
            ("p", "pane"),
            ("t", "tab"),
            ("s", "scroll"),
            ("o", "session"),
            ("a", "appearance"),
            ("l", "lock"),
        ]),
        ("tools", [("g", "git"), ("d", "docker"), ("b", "btop"), ("/", "help")]),
    ],
    "pane": [
        ("move", [("hjkl", "focus"), ("HJKL", "move")]),
        ("size", [("-=", "height"), (",.", "width")]),
        ("split", [("v", "vsplit"), ("s", "split")]),
        ("pane", [("w", "picker"), ("f", "zoom"), ("x", "close")]),
    ],
    "tabmode": [
        ("tab", [("n", "new"), ("x", "close"), ("r", "rename")]),
        ("go", [("hl", "switch"), ("1-9", "goto")]),
    ],
    "scrollmode": [
        ("scroll", [("jk", "line"), ("du", "page"), ("gG", "ends")]),
    ],
    "sessionmode": [
        ("open", [("k", "sessions"), ("a", "agents"), ("o", "overview")]),
        ("cycle", [("[]", "prev/next")]),
    ],
    "appearancemode": [
        ("opacity", [("-=", "adjust"), ("0", "reset")]),
        ("bar", [("v", "sidebar")]),
    ],
    "locked": [
        ("unlock", [("^g", "exit")]),
        ("apps", [("*", "app keys")]),
    ],
}


def iter_hints(mode: str):
    """Every (keys, label) pair for a mode, flattened out of its groups."""
    for group in MODE_HINTS.get(mode, []):
        yield from group[1]
