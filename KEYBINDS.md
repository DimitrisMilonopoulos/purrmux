# Keybindings

Three tiers, arranged so kitty takes as little as possible from the programs
running inside it:

1. **`ctrl+g`** — the leader. Everything infrequent hangs off it, so this is the
   only key kitty takes from your shell and editor.
2. **`alt+…`** — six shortcuts for the hot path, where a leader keystroke every
   time would grate.
3. **`ctrl+shift+…`** — kitty's own namespace; no terminal app competes for it.

The tab bar's mode row shows `^g` while you're just typing, the leader and its
keys once you press it, and a mode's keys once you pick one. **Any unbound key
exits a mode**, so `esc`, `enter` and a mistyped key all cancel. Modes wait
indefinitely — set `map_timeout 2.0` in `override.conf` if you would rather they
expire on idle.

Each key gets its own label by default (`p pane   t tab`), two to a row. For a
compact list of just the keys, grouped (`modes  p t s o a l`), set
`MODE_HINT_STYLE = "keys"` in `tab_bar/config.py`.

Launch kitty with `--single-instance` — session cycling and the agent
picker/overview only see sessions in their own kitty process.

**On macOS, every `alt+…` binding is the Option key.** `os-macos.conf` sets
`macos_option_as_alt yes` so Option registers as Alt rather than composing
Unicode characters. `cmd+t` and `cmd+enter` are mapped there too, alongside
their `ctrl+shift` forms. The leader and everything under it are plain keys, so
they are identical on both platforms.

## Leader — `ctrl+g`

Straight to a tool:

- `g` — lazygit overlay
- `d` — lazydocker overlay
- `b` — btop overlay
- `/` — open this cheatsheet in a tab (`q` to dismiss)

Or into a mode:

- `p` — pane · `t` — tab · `s` — scroll · `o` — session · `a` — appearance ·
  `l` — lock

## Pane mode — `ctrl+g` `p`

Sticky: it stays until you press an unbound key.

- `h` / `j` / `k` / `l` — focus pane left / down / up / right
- `H` / `J` / `K` / `L` — move pane left / down / up / right
- `-` / `=` — shorter / taller
- `,` / `.` — narrower / wider
- `v` — vertical split (cwd)
- `s` — horizontal split (cwd)
- `w` — pane picker (fzf); exits the mode so the picker gets your keys
- `f` — toggle stack (zoom active pane)
- `x` — close pane

## Tab mode — `ctrl+g` `t`

One-shot: it exits after a single action. For repeated tab switching use
`ctrl+shift+up` / `ctrl+shift+down`.

- `n` — new tab (cwd)
- `x` — close tab
- `r` — rename tab
- `h` / `l` — previous / next tab
- `1`–`9` — jump to tab N

## Scroll mode — `ctrl+g` `s`

Sticky.

- `j` / `k` — scroll line down / up
- `d` / `u` — scroll page down / up
- `g` / `G` — scroll home / end

## Session mode — `ctrl+g` `o`

One-shot.

- `k` — session picker (zoxide), in-window overlay
- `a` — agent picker (statuses, ones needing attention first; `ctrl-x` clears
  attention)
- `o` — agent overview: every agent across all sessions, with a live preview of
  its screen
- `]` / `[` — cycle to next / previous session (same as `alt+]` / `alt+[`)

## Appearance mode — `ctrl+g` `a`

Sticky, so opacity can be nudged a step at a time.

- `-` / `=` — decrease / increase opacity
- `0` — reset opacity to default
- `v` — toggle the vertical tab bar (sidebar)
- `b` — hide the tab bar, and bring it back at the same edge; exits the mode,
  being done in one press

## Lock mode — `ctrl+g` `l`

Unknown keys pass through to the running program, which suspends the `alt` tier
too. Use it when an app wants keys this config has taken.

- `ctrl+g` — exit lock mode

## Quick shortcuts — `alt`

- `alt+h` / `alt+j` / `alt+k` / `alt+l` — focus pane left / down / up / right
- `alt+]` / `alt+[` — cycle to next / previous session

## kitty's namespace — `ctrl+shift`

- `ctrl+shift+enter` (`cmd+enter`) — new window (cwd)
- `ctrl+shift+t` (`cmd+t`) — new tab (cwd)
- `ctrl+shift+up` / `ctrl+shift+down` — previous / next tab (replaces kitty's
  line-scroll defaults)

## Outside kitty

- `super+/` — session picker, the same one as `ctrl+g o k`
- `super+o` — the agent deck: every agent running in kitty, with a live mirror
  of the selected one's screen

`super+/` is a quake dropdown, bound in `hypr/binds.lua` to `bin/quake`: a
layer-shell panel anchored to the top edge, so it spans the monitor's full
width — nothing is centred and nothing is truncated. Pressing the key again
hides it.

The quake is a kitty of its own, and that is what keeps the sidebar off it: the
tab bar is an instance-wide option, so a window without one has to be an
instance without one (`quake-kitty.conf`). A second kitty costs ~470ms to start,
so `bin/quake` starts it once and keeps it alive with a hidden window that does
nothing — only the first press after a reboot waits.

The panel itself is not kept. Each press closes whatever is open and creates a
new one, and the picker exiting takes its panel with it, because the panel *is*
that window. Nothing tracks whether a quake is currently on screen, which is
deliberate: versions that hid and re-showed one long-lived panel were all flaky
in the same way, since the hotkey, `hide_on_focus_loss` and the compositor each
changed that state without telling the others. Dismiss with esc.

It drives the main instance over remote control — `--main-listen-on auto` — so
the sessions it opens land there rather than in the dropdown.

`super+o` was a quake too, and is now an ignis popup
(`ignis/modules/agent_deck`), because it wanted two things a second kitty could
not give it: to be reachable from a workspace with no kitty on it, and to leave
a badge in the bar when an agent starts waiting on you. It reads the same state
through the same `session-management/agents.py`, so it and `ctrl+g o o` can
never disagree about what is running.

- macOS has no compositor hotkey for that. kitty registers a "Quick access to
  kitty" entry under System Settings → Keyboard → Keyboard Shortcuts → Services
  → General once you've run `kitten quick-access-terminal` by hand, or a
  launcher (skhd, Hammerspoon, Raycast) can run the full command above directly.
  Untested here — whether the Services route carries the picker arguments
  through is unverified.

## Editing these

`keybinds.conf` is the source of truth. The tab bar's hints live in
`MODE_HINTS` in `tab_bar/config.py`, grouped by hand because the grouping is a
judgement call, so run `python3 tab_bar/check-hints.py` after changing either —
it fails if a hint names a key the conf doesn't bind, and notes keys the conf
binds that no hint mentions. Both hint styles come off that one table.

Note that a bare uppercase letter is not a distinct key to kitty: `H` parses
exactly like `h`, and the later binding silently wins. Write `shift+h`.
