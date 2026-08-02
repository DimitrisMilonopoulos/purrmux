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
# VERTICAL_ACTIVE_MARKER: column drawn at the outer edge of the active row
# ("" disables it) — the "chip" tab style and the footer's mode row only, since
# the "list" style marks the active tab by filling its band instead.
# VERTICAL_SEPARATOR: full-height rule down the inner edge, dividing the
# sidebar from the panes ("" disables it, and the tabs take the column it was
# holding — which also lets the active band run edge to edge).
# VERTICAL_SEPARATOR_AUTO: leave that rule out when the sidebar has a
# background of its own, since the two surfaces then divide themselves and a
# rule on top of that boundary only doubles it.
# VERTICAL_SURFACE: give the sidebar that background even on themes that ship
# no tab_bar_background, by deriving one from the theme and writing it to the
# tab bar screen. Costs no column, unlike the rule it replaces. False leaves
# the bar on the theme's own background, and the rule comes back with it.
# VERTICAL_SHOW_STATUS: the branch of the active tab —
# plus the keyboard mode and its hints — stacked at the bottom of the sidebar.
# VERTICAL_SHOW_AGENT_STATUS: agent status ("working · claude") on the spare row
# under each tab, when kitty gives tabs two rows each.
# VERTICAL_SHOW_TAB_BRANCH: fall back to the tab's git branch on that row when
# it isn't running an agent. Off, because the branch belongs to the session and
# the footer already carries it — and read per tab it is read from that tab's
# cwd, so tabs in one project could disagree about its branch.
VERTICAL_ACTIVE_MARKER = "▎"
VERTICAL_SEPARATOR = "│"
VERTICAL_SEPARATOR_AUTO = True
VERTICAL_SURFACE = True
VERTICAL_SHOW_STATUS = True
VERTICAL_SHOW_AGENT_STATUS = True
VERTICAL_SHOW_TAB_BRANCH = False

# How a tab is drawn in the sidebar.
#   "list"  flat rows: a coloured dot, the title, and a muted second row. The
#           active tab is a filled band rather than a pill. Reads as a list of
#           things rather than a stack of buttons, which is what a column of
#           tabs next to a TUI wants to be.
#   "chip"  the powerline pills the horizontal bar uses.
# The dot is the app's icon where one is known, and an agent's status dot —
# coloured by status — where the tab is running one.
VERTICAL_TAB_STYLE = "list"
VERTICAL_TAB_BULLET = "•"
# Columns between that dot and the title. The second line indents to match, so
# it stays under the title rather than under the dot.
VERTICAL_TAB_ICON_GAP = 2

# Agents report a status into the agent_status user var from the attention hooks
# (hooks/install-attention-hooks.sh). AGENT_EXES are the processes recognised as
# agents when no hook has reported yet, so a status can still be derived.
# How the sidebar's bottom block is drawn. "minimal" is flat — a coloured icon
# and plain text — because powerline caps read as chunky pills once they are
# stacked in a narrow column; "chip" matches the tab pills instead.
VERTICAL_FOOTER_STYLE = "minimal"

# Blank rows inside the footer, which otherwise stacks four unrelated things
# into a solid block. VERTICAL_FOOTER_SPACING separates the groups — keyboard
# mode (with its hints), attention, then branch and session — and
# VERTICAL_FOOTER_BOTTOM_PAD holds the last row off the bottom edge. That one is
# 0 so the session name ends the column flush against it. Both are the first
# thing given up when the sidebar runs short of rows, so spacing never costs
# you a hint.
VERTICAL_FOOTER_SPACING = 1
VERTICAL_FOOTER_BOTTOM_PAD = 0

# Size of the session name — the last row of the footer, and the thing the rest
# of the footer qualifies — as a (numerator, denominator) fraction of every
# other row. kitty's text sizing protocol grows text only by handing it whole
# extra cells and shrinks it by a fraction within them, so 3/2 is two cells with
# the glyph drawn at three quarters of them. Anything above 1 therefore costs a
# second row and two columns per character however gentle the fraction, and only
# whole multiples fill their cells: (3, 2) reads as letter-spaced and leaves a
# sliver of empty box under the name, (2, 1) is double and tight.
#
# So this stays 1: the row is marked as the anchor by weight instead, drawn bold
# and at full brightness like the attention row (see footer_cell).
VERTICAL_SESSION_SCALE = (1, 1)

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
MODE_HINT_STYLE = "labels"

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
    # A shell has no app to name, and its title is a path: say so with a folder.
    "fish": "",
    "zsh": "",
    "bash": "",
    "sh": "",
}

FOLDER_ICON = " "
BRANCH_ICON = " "
MODE_ICON = "󰘳 "
ZOOM_ICON = " "
SESSION_ICON = " "
# Two glyphs, in color1 from VERTICAL_FOOTER_ICON_COLORS: nf-md-robot says what
# wants you, and the "!" that it is waiting. They need the space between them — this
# is a Nerd Font rather than a Nerd Font Mono, so its icons are drawn two cells
# wide, and kitty shrinks one to a single cell rather than let it run into a
# neighbour that isn't blank.
ATTENTION_ICON = "\U000f06a9 ! "

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
