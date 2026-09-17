#!/usr/bin/env bash
set -euo pipefail

# Registers bin/kitty-agent as an MCP server called "kitty-agents", so the
# agents you run can spawn and drive each other.
#
# Unlike install-attention-hooks.sh, which had to write the JSON itself, all
# three agents ship an `mcp add` of their own — so the CLI is the path here and
# hand-editing is the fallback, not the other way round. That matters more than
# it sounds: ~/.claude.json carries live session state that a running Claude
# Code rewrites underneath you, ~/.codex/config.toml holds the hook-trust
# hashes and stdlib tomllib cannot write TOML back, and opencode.jsonc has
# comments that json.dump would eat. Each agent's own CLI is the only writer
# that knows how to keep its own file.
#
# Safe to rerun: each add is preceded by a remove.

script_dir=$(CDPATH= cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
server=$(CDPATH= cd "$script_dir/.." && pwd)/bin/kitty-agent
name=kitty-agents

if [ ! -x "$server" ]; then
    echo "[agent-mcp-install] $server is not executable" >&2
    exit 1
fi

install_claude_mcp() {
    if ! command -v claude >/dev/null 2>&1; then
        echo '[agent-mcp-install] skip claude: claude command not found'
        return
    fi

    echo "[agent-mcp-install] registering $name with Claude Code"
    claude mcp remove --scope user "$name" >/dev/null 2>&1 || true
    if claude mcp add --scope user "$name" -- "$server" mcp; then
        echo '[agent-mcp-install] registered with Claude Code'
    else
        echo '[agent-mcp-install] claude mcp add failed; add it by hand with:' >&2
        echo "  claude mcp add --scope user $name -- $server mcp" >&2
    fi
}

install_codex_mcp() {
    if ! command -v codex >/dev/null 2>&1; then
        echo '[agent-mcp-install] skip codex: codex command not found'
        return
    fi

    echo "[agent-mcp-install] registering $name with Codex"
    codex mcp remove "$name" >/dev/null 2>&1 || true
    if codex mcp add "$name" -- "$server" mcp; then
        echo '[agent-mcp-install] registered with Codex'
    else
        echo '[agent-mcp-install] codex mcp add failed; add it by hand with:' >&2
        echo "  codex mcp add $name -- $server mcp" >&2
    fi
}

install_opencode_mcp() {
    if ! command -v opencode >/dev/null 2>&1; then
        echo '[agent-mcp-install] skip opencode: opencode command not found'
        return
    fi

    echo "[agent-mcp-install] registering $name with OpenCode"
    if opencode mcp add "$name" -- "$server" mcp 2>/dev/null; then
        echo '[agent-mcp-install] registered with OpenCode'
        return
    fi

    # opencode's mcp add is interactive in some versions. Its config is JSONC,
    # so printing the snippet beats rewriting the file and losing its comments.
    echo '[agent-mcp-install] could not register with OpenCode automatically.'
    echo "[agent-mcp-install] add this under \"mcp\" in ${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.jsonc:"
    cat <<JSON
    "$name": {
      "type": "local",
      "command": ["$server", "mcp"],
      "enabled": true
    }
JSON
}

echo '[agent-mcp-install] start'
install_claude_mcp
install_codex_mcp
install_opencode_mcp
echo '[agent-mcp-install] done'
echo "[agent-mcp-install] smoke test: $server list"
echo '[agent-mcp-install] all three read their MCP config at startup — restart the agent'
