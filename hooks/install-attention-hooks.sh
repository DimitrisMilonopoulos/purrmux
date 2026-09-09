#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
xdg_config_home=${XDG_CONFIG_HOME:-$HOME/.config}
codex_home=${CODEX_HOME:-$HOME/.codex}

agent_source="$script_dir/agent-attention-kitty.sh"
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

# Registers the reporter in a JSON hooks config. Claude Code keeps its hooks in
# settings.json and Codex in hooks.json, but both nest the same shape under a
# "hooks" key, so one writer serves both.
#   $1 config file, $2 installed reporter, $3 agent name,
#   $4 JSON [[event, matcher-or-null, mode], ...]
register_hooks() {
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import json
import os
import sys
import tempfile

config_path, hook_path, agent, events_json = sys.argv[1:5]
events = json.loads(events_json)

# Any command mentioning the reporter is ours, whatever it was called when it
# was registered, so a rename cannot leave a stale copy behind.
PRUNE_MARKER = "attention-kitty.sh"


def hook_command(mode):
    return f"{hook_path} {mode} {agent}"


def load_config(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read().strip()
    if not content:
        return {}
    return json.loads(content)


def ensure_hook(config, event, matcher, command):
    hooks = config.setdefault("hooks", {})
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


def prune_hooks(config):
    """Drop our own registrations, so rerunning cannot stack stale modes.

    The events a mode is attached to change as the hook grows; leaving an
    earlier registration behind would run two modes per event.
    """
    hooks = config.get("hooks")
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
                if PRUNE_MARKER not in str(hook.get("command", ""))
            ]
            if not entry["hooks"]:
                entries.remove(entry)
        if not entries:
            del hooks[event]


config = load_config(config_path)
prune_hooks(config)
for event, matcher, mode in events:
    ensure_hook(config, event, matcher, hook_command(mode))

config_dir = os.path.dirname(config_path)
os.makedirs(config_dir, exist_ok=True)
fd, tmp_path = tempfile.mkstemp(prefix=f".{os.path.basename(config_path)}.tmp.", dir=config_dir, text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")
    os.replace(tmp_path, config_path)
finally:
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)
PY
}

install_claude_attention() {
  if ! command -v claude >/dev/null 2>&1; then
    echo '[attention-install] skip claude: claude command not found'
    return
  fi

  local hook_target="$HOME/.claude/hooks/agent-attention-kitty.sh"
  local settings_target="$HOME/.claude/settings.json"

  echo '[attention-install] installing Claude attention hook'
  install_file "$agent_source" "$hook_target" 0755
  echo "[attention-install] updating $settings_target"

  # Statuses the tab bar shows under each agent tab, and when it flags attention.
  register_hooks "$settings_target" "$hook_target" claude '[
    ["Notification", "permission_prompt|idle_prompt|elicitation_dialog", "blocked"],
    ["Stop", null, "done"],
    ["UserPromptSubmit", null, "working"],
    ["PostToolUse", "*", "working"],
    ["SessionStart", null, "idle"],
    ["SessionEnd", "*", "clear"]
  ]'

  # The reporter used to be installed under its old name; a leftover copy would
  # keep firing from any registration we did not write.
  rm -f "$HOME/.claude/hooks/claude-attention-kitty.sh"

  echo '[attention-install] installed Claude attention hook'
}

install_codex_attention() {
  if ! command -v codex >/dev/null 2>&1; then
    echo '[attention-install] skip codex: codex command not found'
    return
  fi

  local hook_target="$codex_home/hooks/agent-attention-kitty.sh"
  local hooks_target="$codex_home/hooks.json"

  echo '[attention-install] installing Codex attention hook'
  install_file "$agent_source" "$hook_target" 0755
  echo "[attention-install] updating $hooks_target"

  # Codex fires the same events as Claude Code, save for the permission prompt:
  # it has a PermissionRequest event of its own rather than a Notification kind.
  register_hooks "$hooks_target" "$hook_target" codex '[
    ["PermissionRequest", null, "blocked"],
    ["Stop", null, "done"],
    ["UserPromptSubmit", null, "working"],
    ["PostToolUse", "*", "working"],
    ["SessionStart", null, "idle"],
    ["SessionEnd", null, "clear"]
  ]'

  # Codex reads hooks from hooks.json or from config.toml, and warns when one
  # layer uses both. We only write hooks.json, so say so rather than let the
  # warning turn up unexplained.
  if python3 - "$codex_home/config.toml" <<'PY'
import os
import sys
import tomllib

path = sys.argv[1]
if not os.path.exists(path):
    sys.exit(1)
with open(path, "rb") as handle:
    config = tomllib.load(handle)
hooks = config.get("hooks")
sys.exit(0 if isinstance(hooks, dict) and hooks.keys() - {"state"} else 1)
PY
  then
    echo "[attention-install] note: $codex_home/config.toml also declares hooks;" \
      'Codex prefers a single representation per layer, so move those into hooks.json'
  fi

  echo '[attention-install] installed Codex attention hook'
  echo '[attention-install] Codex asks to trust new hooks on its next start —'\
    'until you accept, it will not run them'
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
install_codex_attention
install_opencode_attention
echo '[attention-install] done'
