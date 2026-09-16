"""Drop an agent's attention as soon as you actually look at it.

The hooks in ``hooks/`` raise ``agent_attention`` when an agent blocks or
finishes while you are elsewhere, and until now nothing lowered it again: the
pickers *hide* attention for the window you have focused, but the user var
stayed set, so the tab bar's count came straight back the moment you looked
away. Clearing it was a thing you had to remember to do by hand (``ctrl-x`` in
the overview), which is not what "I have seen this" should cost.

Focus is the signal. A watcher runs inside kitty and hears about it directly,
so the count drops on the keystroke that takes you there rather than on a poll.

Wired up by ``watcher watchers/agent-attention.py`` in kitty.conf. kitty applies
that to windows created *after* it is set, so windows already running when it
was added keep the old behaviour until they are restarted — the agents service
in ignis sweeps those, and this makes that sweep redundant for everything new.
"""

ATTENTION_VARS = ("agent_attention", "agent_attention_source", "agent_attention_at")


def on_focus_change(boss, window, data):
    """Focusing a window is as good as saying you have read it."""
    if not data.get("focused"):
        return
    if window.user_vars.get("agent_attention") != "1":
        return
    # The status is left alone: what the agent is doing is still true, and the
    # overview colours its dot by it. Only the "wants you" flag is spent.
    for key in ATTENTION_VARS:
        window.set_user_var(key, None)
