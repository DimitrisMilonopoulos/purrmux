#!/usr/bin/env bash
# Seed the gitignored override.conf, so there's an obvious place to customize
# purrmux without forking it. Safe to rerun: an existing override.conf is left
# exactly as it is, never overwritten.
set -euo pipefail

script_dir=$(CDPATH= cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
target="$script_dir/override.conf"

log() {
  echo "[purrmux-setup] $*"
}

expected_dir="${XDG_CONFIG_HOME:-$HOME/.config}/kitty"
if [[ $script_dir != "$expected_dir" ]]; then
  log "warning: this checkout lives at $script_dir, not $expected_dir"
  log "         kitty.conf and keybinds.conf hardcode \$HOME/.config/kitty in"
  log "         startup_session and every launch line — adjust them or move the"
  log "         checkout, or the pickers and tool tabs will not start"
fi

if [[ -e $target ]]; then
  log "override.conf already exists, leaving it alone"
else
  cat > "$target" <<'EOF'
# purrmux user overrides.
#
# kitty.conf ends with `globinclude override.conf`, so anything here is included
# last and beats every setting above it. This file is gitignored, so it survives
# `git pull` and never conflicts.
#
# See "Customizing without forking" in README.md for the settings worth
# changing. Reload without restarting kitty: ctrl+shift+f5.
EOF
  log "created override.conf"
fi

log "edit $target to change any setting"
log "optional: hooks/install-attention-hooks.sh — agent status and attention in the tab bar"
