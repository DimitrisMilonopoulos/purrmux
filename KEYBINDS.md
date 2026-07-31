# Keybindings

Leader-style mode switches: enter a mode, press keys, `esc` / `enter` / same mode key to exit.

Launch kitty with `--single-instance` — session cycling and the agent picker/overview only see sessions in their own kitty process.

**On macOS, every `alt+…` binding below is the Option key.** `os-macos.conf` sets `macos_option_as_alt yes` so Option registers as Alt rather than composing Unicode characters — without it none of the leader keys fire at all. kitty spells that modifier `opt`, which is what the mode headings show in parentheses; the two are interchangeable everywhere. `cmd+t` and `cmd+enter` are mapped there too, alongside their `ctrl+shift` forms.

## Global

- `ctrl+shift+enter` (`cmd+enter`) — new window (cwd)
- `ctrl+shift+t` (`cmd+t`) — new tab (cwd)
- `alt+h` / `alt+j` / `alt+k` / `alt+l` (`opt+…`) — focus pane left / down / up / right
- `ctrl+shift+up` / `ctrl+shift+down` — previous / next tab (replaces kitty's line-scroll defaults)
- `alt+]` / `alt+[` (`opt+…`) — cycle to next / previous session
- `ctrl+shift+/` — show this keybinds overlay

## Pane mode — `alt+p` (`opt+p`)

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

## Tab mode — `alt+t` (`opt+t`)

- `n` — new tab (cwd)
- `x` — close tab
- `h` / `l` — previous / next tab
- `r` — rename tab
- `v` — toggle the vertical tab bar (sidebar)
- `1`–`9` — jump to tab N
- `esc` / `enter` / `alt+t` — exit mode

## Scroll mode — `alt+s` (`opt+s`)

- `j` / `k` — scroll line down / up
- `d` / `u` — scroll page down / up
- `g` / `G` — scroll home / end
- `esc` / `enter` / `alt+s` — exit mode

## Opacity mode — `alt+o` (`opt+o`)

- `-` / `=` — decrease / increase opacity
- `0` — reset to default
- `esc` / `enter` / `alt+o` — exit mode

## Lock mode — `alt+g` (`opt+g`)

Unknown keys pass through to the running program (lets shell/app shortcuts bypass kitty leaders).

- `alt+shift+g` (`opt+shift+g`) — exit mode

## Chord sequences

- `ctrl+a` → `k` — session picker (zoxide), in-window overlay
- `ctrl+a` → `a` — agent picker (statuses, ones needing attention first; `ctrl-x` clears attention)
- `ctrl+a` → `o` — agent overview: every agent across all sessions, with a live preview of its screen
- `ctrl+a` → `g` — lazygit overlay
- `ctrl+a` → `d` — lazydocker overlay
- `ctrl+a` → `b` — btop overlay
- `ctrl+a` → `v` — toggle the vertical tab bar (sidebar)

## Outside kitty

- Quake dropdown session picker — bind a compositor hotkey to
  `kitten quick-access-terminal python3 ~/.config/kitty/session-management/kitty-zoxide-sessions.py --ansi --target=window --main-listen-on auto`
  (see `quick-access-terminal.conf`). Works even when kitty isn't focused.
- macOS has no compositor hotkey for that. kitty registers a "Quick access to kitty"
  entry under System Settings → Keyboard → Keyboard Shortcuts → Services → General
  once you've run `kitten quick-access-terminal` by hand, or a launcher (skhd,
  Hammerspoon, Raycast) can run the full command above directly. Untested here —
  whether the Services route carries the picker arguments through is unverified.
