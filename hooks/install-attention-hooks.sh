#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
xdg_config_home=${XDG_CONFIG_HOME:-$HOME/.config}

claude_source="$script_dir/claude-attention-kitty.sh"
opencode_source="$script_dir/opencode-attention-kitty.js"

install_file() {
  local source=$1
  local target=$2
  local mode=$3
  local target_dir

  target_dir=$(dirname "$target")

  mkdir -p "$target_dir"
  echo "[attention-install] installing $target"
  if cp "$source" "$target" && chmod "$mode" "$target"; then
    echo "[attention-install] installed $target"
    return
  fi
  echo "[attention-install] failed to install $target"
  return 1
}

install_claude_attention() {
  if ! command -v claude >/dev/null 2>&1; then
    echo '[attention-install] skip claude: claude command not found'
    return
  fi

  local hook_target="$HOME/.claude/hooks/claude-attention-kitty.sh"
  local settings_target="$HOME/.claude/settings.json"

  echo '[attention-install] installing Claude attention hook'
  install_file "$claude_source" "$hook_target" 0755
  echo "[attention-install] updating $settings_target"

  python3 - "$settings_target" "$hook_target" <<'PY'
import json
import os
import sys
import tempfile

settings_path, hook_path = sys.argv[1:3]


def hook_command(mode):
    return f"{hook_path} {mode}"


def load_settings(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read().strip()
    if not content:
        return {}
    return json.loads(content)


def ensure_hook(settings, event, matcher, command):
    hooks = settings.setdefault("hooks", {})
    entries = hooks.setdefault(event, [])
    target_hook = {"type": "command", "command": command}

    for entry in entries:
        entry_matcher = entry.get("matcher")
        if matcher is None:
            matcher_matches = "matcher" not in entry
        else:
            matcher_matches = entry_matcher == matcher
        if not matcher_matches:
            continue

        entry_hooks = entry.setdefault("hooks", [])
        if target_hook not in entry_hooks:
            entry_hooks.append(target_hook)
        return

    new_entry = {"hooks": [target_hook]}
    if matcher is not None:
        new_entry["matcher"] = matcher
    entries.append(new_entry)


def prune_hooks(settings, command_prefix):
    """Drop our own registrations, so rerunning cannot stack stale modes.

    The events a mode is attached to change as the hook grows; leaving an
    earlier registration behind would run two modes per event.
    """
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return

    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        for entry in list(entries):
            entry_hooks = entry.get("hooks")
            if not isinstance(entry_hooks, list):
                continue
            entry["hooks"] = [
                hook
                for hook in entry_hooks
                if not str(hook.get("command", "")).startswith(command_prefix)
            ]
            if not entry["hooks"]:
                entries.remove(entry)
        if not entries:
            del hooks[event]


settings = load_settings(settings_path)
prune_hooks(settings, hook_path)
# Statuses the tab bar shows under each agent tab, and when it flags attention.
ensure_hook(settings, "Notification", "permission_prompt|idle_prompt|elicitation_dialog", hook_command("blocked"))
ensure_hook(settings, "Stop", None, hook_command("done"))
ensure_hook(settings, "UserPromptSubmit", None, hook_command("working"))
ensure_hook(settings, "PostToolUse", "*", hook_command("working"))
ensure_hook(settings, "SessionStart", None, hook_command("idle"))
ensure_hook(settings, "SessionEnd", "*", hook_command("clear"))

settings_dir = os.path.dirname(settings_path)
os.makedirs(settings_dir, exist_ok=True)
fd, tmp_path = tempfile.mkstemp(prefix=".settings.json.tmp.", dir=settings_dir, text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    os.replace(tmp_path, settings_path)
finally:
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)
PY

  echo '[attention-install] installed Claude attention hook'
}

install_opencode_attention() {
  if ! command -v opencode >/dev/null 2>&1; then
    echo '[attention-install] skip opencode: opencode command not found'
    return
  fi

  local plugin_target="$xdg_config_home/opencode/plugins/opencode-attention-kitty.js"
  echo '[attention-install] installing OpenCode attention plugin'
  install_file "$opencode_source" "$plugin_target" 0644
  echo '[attention-install] installed OpenCode attention plugin'
}

echo '[attention-install] start'
install_claude_attention
install_opencode_attention
echo '[attention-install] done'
