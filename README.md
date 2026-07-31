# purrmux

A tmux-ish kitty config — modal pane/tab/scroll/lock navigation, zoxide-backed session management, fzf pane picker, lazygit/lazydocker tool tabs, and a custom tab bar.

See [`KEYBINDS.md`](KEYBINDS.md) for the full cheatsheet. While running, `ctrl+shift+/` opens it in a tab (`q` to dismiss).

## Prerequisites

**Required**

- [kitty](https://sw.kovidgoyal.net/kitty/) — recent enough to support `globinclude` and the `KITTY_OS` variable
- Python 3 — ships with both distros; used by the tab bar and session/tab/tool scripts
- [fish](https://fishshell.com/) — set as `shell` in `kitty.conf`; change the line (or use `override.conf` below) if you use zsh/bash
- [JetBrainsMono Nerd Font](https://www.nerdfonts.com/) — for the tab-bar icons and powerline glyphs

**Used by the keybinds / overlays**

- [fzf](https://github.com/junegunn/fzf) — session picker, pane picker
- [zoxide](https://github.com/ajeetdsouza/zoxide) — source of session candidates
- [bat](https://github.com/sharkdp/bat) + `less` — render the `ctrl+shift+/` keybinds tab

**Optional**

- [lazygit](https://github.com/jesseduffield/lazygit) — `alt+p g` and `ctrl+a>g`
- [lazydocker](https://github.com/jesseduffield/lazydocker) — `alt+p d` and `ctrl+a>d`
- `nvim` (or any `$EDITOR`) — for editing session files via the session picker

## Screenshot

![purrmux in action — vertical tab bar with agent statuses and the session/branch footer](assets/2026-07-31-14-33-11.png)

## Install

```sh
git clone <this-repo> ~/.config/kitty
```

The `startup_session` and all script paths assume `~/.config/kitty`; if you clone elsewhere you'll need to adjust `kitty.conf` and the `keybinds.conf` launch lines.

## Platform support

Works on Linux and macOS. OS-specific bits live in `os-linux.conf` and `os-macos.conf`, auto-selected via:

```
include os-${KITTY_OS}.conf
```

Currently split that way:

- **`listen_on`** — Linux uses an abstract unix socket (`unix:@kitty-…`); macOS uses a filesystem socket under `/tmp`.
- **`bell_path`** — Linux points at the freedesktop stereo bell; macOS falls back to kitty's default bell (add your own `bell_path /System/Library/Sounds/Glass.aiff` in `os-macos.conf` if desired).

## Customizing without forking

`kitty.conf` ends with:

```
globinclude override.conf
```

Drop a file named `override.conf` next to `kitty.conf` with any directives you want to change. Because it's included last, it overrides everything above it. Examples:

```
# override.conf

# use zsh instead of fish
shell zsh

# dial opacity back
background_opacity 0.9

# rebind the keybinds overlay
map ctrl+shift+h launch --type=tab --tab-title="keybinds" sh -c 'bat --color=always --style=plain --language=md "$HOME/.config/kitty/KEYBINDS.md" | less -R'
```

`override.conf` is gitignored, so it won't clash with `git pull`s. The glob matches nothing if the file is absent — no error.

## Vertical tab bar (sidebar)

kitty 0.48 can put the tab bar on the left or right edge (`tab_bar_edge left`). `ctrl+a>v` (or `v` in tab mode) toggles between the bottom strip and a sidebar at runtime — no restart, no config edit:

```sh
tab_bar/toggle-edge.py [toggle|on|off|left|right|status]
```

There is no remote-control command for setting an option, so the script reloads the config with `tab_bar_edge`/`tab_title_max_length`/`tab_bar_align` overrides (`kitten @ load-config -o …`) and reloads without them to go back. Being a config reload, it also resets runtime-only tweaks such as `set_background_opacity` to their configured values. State lives in `$XDG_RUNTIME_DIR/kitty-tab-bar-edge-*`, per kitty instance.

The custom tab bar draws a different layout in sidebar mode (`tab_bar/vertical.py`):

- **Tabs** as one chip per row from the top, with an active-tab marker at the outer edge, and a full-height rule dividing the sidebar from the panes — kitty has no option for a tab bar border, so the tab bar paints that column itself.
- **Agent status** on the spare row kitty gives each tab (`● working · claude`), for tabs running an agent only.
- **A footer** carrying what the horizontal bar keeps in its side sections — agent attention, session, git branch, plus the keyboard mode (including zoom) and its hints. Drawn flat rather than as powerline chips, since stacked caps read as chunky pills in a narrow column, with each row's icon coloured from the theme palette. It's dropped entirely when the tabs need the rows.

Knobs at the top of `tab_bar/config.py`: `VERTICAL_ACTIVE_MARKER`, `VERTICAL_SEPARATOR`, `VERTICAL_SHOW_STATUS`, `VERTICAL_SHOW_AGENT_STATUS`, `VERTICAL_FOOTER_STYLE`, `VERTICAL_FOOTER_ICON_COLORS`, and `VERTICAL_SECONDARY_TEXT_SCALE` (font size of the status and hint rows, via kitty's text sizing protocol — chips can't scale, their borders are glyphs). Sidebar side and width live in `tab_bar/toggle-edge.py` (`SIDEBAR_EDGE`, `SIDEBAR_CELLS`).

To start in sidebar mode instead, put `tab_bar_edge left` in `override.conf`.

## Agent attention hooks

The custom tab bar and `ctrl+a>a` attention picker can show agent windows that need attention.

Install the bundled attention hooks/plugins:

```sh
~/.config/kitty/hooks/install-attention-hooks.sh
```

The installer is safe to rerun. It conditionally installs only what is available on your `PATH`:

- If `claude` exists, it installs `claude-attention-kitty.sh` into `~/.claude/hooks/` and registers the `set` / `clear` hooks in `~/.claude/settings.json`.
- If `opencode` exists, it installs `opencode-attention-kitty.js` into `${XDG_CONFIG_HOME:-~/.config}/opencode/plugins/`.

Hook/plugin files and Claude settings are replaced atomically. Reruns prune the installer's own registrations before adding them back, so changing which events a mode is attached to can't leave two modes firing per event. OpenCode loads local plugins on startup, so restart OpenCode after installing the plugin; Claude Code reads `settings.json` hooks at startup too.

Both hooks report state into kitty user vars: `agent_attention` (plus `agent_name`, `agent_attention_source`, `agent_attention_at`) flags a window that wants you while you're looking elsewhere, and `agent_status` carries what the agent is doing — which the sidebar draws on the row under each agent tab, dot coloured from the theme palette:

| status | Claude event | OpenCode event | dot |
| --- | --- | --- | --- |
| `working` | `UserPromptSubmit`, `PostToolUse` | `tui.prompt.append`, `tool.execute.before` | yellow |
| `blocked` | `Notification` (permission/idle/elicitation) | `question.asked`, `permission.asked` | red |
| `done` | `Stop` | `session.idle` | blue |
| `error` | — | `session.error` | red |
| `idle` | `SessionStart` | — | muted `○` |

`ctrl+a>o` opens the overview — every agent in every session, grouped, with a live preview of that agent's actual screen (`kitten @ get-text`), so you see the real progress rather than a summary of it. It refreshes itself: fzf listens on a loopback port and a ticker in the script posts `reload` to it every couple of seconds, keeping statuses, ages and counts current. Enter focuses the window, `ctrl-x` clears its attention, `ctrl-r` refreshes now. The `for` column is the age of `agent_status_at` — a transition time for one-shot statuses like `blocked`, and a heartbeat while `working`.

`ctrl+a>a` lists the same statuses: every agent window, the ones wanting you first (`!`), then by status — `blocked`, `error`, `waiting`, `done`, `working`, `idle`. `ctrl-x` there drops a window's attention but keeps its status, since the agent is still running. Pass `--attention-only` to get the old attention-just-the-alerts list.

`blocked`, `done` and `error` also raise attention when the window isn't focused. Tabs running an agent that hasn't reported (no hooks installed, or a fresh session) fall back to `waiting` when attention is set and `running` otherwise, based on the process in `AGENT_EXES`.

## Security note

`allow_remote_control yes` with `listen_on` is required by the session/pane/tool scripts (they call `kitten @ ls`, `focus-window`, etc.). The socket is per-user (local-only, not network-exposed), but any process running as your user can drive kitty — running commands and reading pane contents. If that's not acceptable for your threat model, set `allow_remote_control no` in `override.conf` and expect the session picker, pane picker, and lazygit/lazydocker launchers to stop working.
