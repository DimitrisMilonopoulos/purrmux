# Keybindings

Leader-style mode switches: enter a mode, press keys, `esc` / `enter` / same mode key to exit.

## Global

- `ctrl+shift+enter` — new window (cwd)
- `ctrl+shift+t` — new tab (cwd)
- `alt+h` / `alt+j` / `alt+k` / `alt+l` — focus pane left / down / up / right
- `alt+]` / `alt+[` — cycle to next / previous session
- `ctrl+shift+/` — show this keybinds overlay

## Pane mode — `alt+p`

- `h` / `j` / `k` / `l` — focus pane left / down / up / right
- `H` / `J` / `K` / `L` — move pane left / down / up / right
- `-` / `=` — shorter / taller
- `,` / `.` — narrower / wider
- `v` — vertical split (cwd)
- `s` — horizontal split (cwd)
- `w` — open pane picker (fzf)
- `g` — focus-or-launch lazygit tool tab
- `d` — focus-or-launch lazydocker tool tab
- `f` — toggle stack (zoom active pane)
- `x` — close pane
- `esc` / `enter` / `alt+p` — exit mode

## Tab mode — `alt+t`

- `n` — new tab (cwd)
- `x` — close tab
- `h` / `l` — previous / next tab
- `r` — rename tab
- `v` — toggle the vertical tab bar (sidebar)
- `1`–`9` — jump to tab N
- `esc` / `enter` / `alt+t` — exit mode

## Scroll mode — `alt+s`

- `j` / `k` — scroll line down / up
- `d` / `u` — scroll page down / up
- `g` / `G` — scroll home / end
- `esc` / `enter` / `alt+s` — exit mode

## Opacity mode — `alt+o`

- `-` / `=` — decrease / increase opacity
- `0` — reset to default
- `esc` / `enter` / `alt+o` — exit mode

## Lock mode — `alt+g`

Unknown keys pass through to the running program (lets shell/app shortcuts bypass kitty leaders).

- `alt+shift+g` — exit mode

## Chord sequences

- `ctrl+a` → `k` — session picker (zoxide), in-window overlay
- `ctrl+a` → `a` — agent picker (statuses, ones needing attention first; `ctrl-x` clears attention)
- `ctrl+a` → `o` — agent overview: every agent across all sessions, with a live preview of its screen
- `ctrl+a` → `g` — lazygit overlay
- `ctrl+a` → `d` — lazydocker overlay
- `ctrl+a` → `b` — btop overlay
- `ctrl+a` → `v` — toggle the vertical tab bar (sidebar)

## Global

- Quake dropdown session picker — bind a compositor hotkey to
  `kitten quick-access-terminal python3 ~/.config/kitty/session-management/kitty-zoxide-sessions.py --ansi --target=window --main-listen-on auto`
  (see `quick-access-terminal.conf`). Works even when kitty isn't focused.
