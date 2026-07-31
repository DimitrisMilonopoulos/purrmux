import { appendFileSync } from "node:fs"

const LOG_PATH = "/tmp/opencode-kitty-attention.log"

const log = (message) => {
  try {
    appendFileSync(LOG_PATH, `[${new Date().toISOString()}] ${message}\n`)
  } catch {}
}

const logEventDetails = (type, event) => {
  if (type !== "session.status" && type !== "question.asked" && type !== "permission.asked") return
  try {
    log(`event-detail ${type} ${JSON.stringify(event)}`)
  } catch (error) {
    log(`event-detail ${type} failed: ${error}`)
  }
}

const envWindowID = () => String(process.env.KITTY_WINDOW_ID || "").trim()
let targetWindowID = envWindowID()

const resultStatus = (result) => String(result?.exitCode ?? result?.exit_code ?? "ok")

const resolveFocusedWindowID = async ($) => {
  const result = await $`kitten @ ls --match state:focused`.quiet().nothrow()
  if ((result.exitCode ?? 0) !== 0) return ""
  try {
    const data = JSON.parse(String(result.stdout || ""))
    for (const osWindow of data) {
      for (const tab of osWindow.tabs || []) {
        for (const window of tab.windows || []) {
          if (window.is_focused && Number.isInteger(window.id)) return String(window.id)
        }
      }
    }
  } catch (error) {
    log(`failed to parse focused window: ${error}`)
  }
  return ""
}

const windowID = () => targetWindowID || envWindowID()

const isFocused = async ($, id) => {
  const match = `id:${id} and state:focused and state:parent_focused`
  try {
    await $`kitten @ ls --match ${match}`.quiet()
    return true
  } catch {
    return false
  }
}

// Reports the agent state into kitty user vars: agent_status is what the tab bar
// draws under the tab, agent_attention flags a window you are not watching.
// Pass source = null for statuses that do not want you (working).
const setState = async ($, status, source, id = windowID()) => {
  if (!id) {
    log(`state skipped for ${status}: no window id`)
    return
  }

  const match = `id:${id}`
  const wants = source !== null && !(await isFocused($, id))

  // agent_status_at is when the status was last reported; the overview shows it
  // as the agent's age.
  const now = String(Math.floor(Date.now() / 1000))

  if (wants) {
    const result = await $`kitten @ set-user-vars --match ${match} agent_status=${status} agent_status_at=${now} agent_name=opencode agent_attention=1 agent_attention_source=${source} agent_attention_at=${now}`
      .quiet()
      .nothrow()
    log(`state ${match} status=${status} source=${source}: ${resultStatus(result)}`)
    return
  }

  const result = await $`kitten @ set-user-vars --match ${match} agent_status=${status} agent_status_at=${now} agent_name=opencode agent_attention agent_attention_source agent_attention_at`
    .quiet()
    .nothrow()
  log(`state ${match} status=${status}: ${resultStatus(result)}`)
}

export const OpenCodeKittyAttention = async ({ $ }) => {
  if (!targetWindowID) targetWindowID = await resolveFocusedWindowID($)
  log(`loaded envWindowID=${envWindowID() || "none"} targetWindowID=${targetWindowID || "none"}`)
  if (!windowID()) return {}

  try {
    await $`which kitten`.quiet()
  } catch {
    log("disabled: kitten not found")
    return {}
  }

  return {
    event: async ({ event }) => {
      const type = String(event?.type || "")
      log(`event ${type || "unknown"}`)
      logEventDetails(type, event)
      if (type === "session.idle") {
        await setState($, "done", type)
      }
      if (type === "session.error") {
        await setState($, "error", type)
      }
      if (type === "question.asked" || type === "permission.asked") {
        await setState($, "blocked", type)
      }
      if (type === "tui.prompt.append" || type === "tui.command.execute") {
        await setState($, "working", null)
      }
    },
    "tool.execute.before": async () => {
      await setState($, "working", null)
    },
    "command.execute.before": async () => {
      await setState($, "working", null)
    },
  }
}
