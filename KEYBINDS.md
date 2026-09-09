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

Sticky.

- `-` / `=` — decrease / increase opacity
- `0` — reset opacity to default
- `v` — toggle the vertical tab bar (sidebar)
- `b` — hide the tab bar, and bring it back at the same edge

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

- Quake dropdown session picker — bind a compositor hotkey to
  `kitten quick-access-terminal python3 ~/.config/kitty/session-management/kitty-zoxide-sessions.py --ansi --target=window --main-listen-on auto`
  (see `quick-access-terminal.conf`). Works even when kitty isn't focused.
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
