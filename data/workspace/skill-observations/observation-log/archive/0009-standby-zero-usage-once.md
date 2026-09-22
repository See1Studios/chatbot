---
id: 9
title: "First message after restart occasionally reports usage=0 (all zero) despite a correct assistant reply"
status: actioned
type: open-source
skill: [chatbot-self-improve]
proposes_skill: []
siblings_checked: none (no skill-families.md registry in this workspace)
area: Chat Host Process Architecture — standby pool vs. per-turn usage/token reporting
date: 2026-09-16
session_context: External SSH audit (GameDeveloper/Claude) verifying newly-added per-turn token usage display (실장님 request), right after a server restart that activated both the standby-pool prewarm feature and 냥피디's own usage/duration_seconds parsing.
resolved: 2026-09-17
resolution: Deliberately did NOT implement the suggested approach (a second reader logging the standby's raw stdout from spawn time, before adoption) -- that would create a genuine new race, with two threads reading the same pipe once the process is adopted and the real _read_stdout() reader starts. Added a risk-free diagnostic instead -- AgySession._spawn() now tags itself with self._adopted_standby (warm-adopted vs. cold-spawned), and the result handler logs a WARN line (sid/conversation_id/adopted_standby) to stderr whenever a session's very first assistant turn has usage present but every token field is zero. Still unreproduced; a recurrence will now leave a trail to confirm or rule out the standby-adoption-timing correlation without touching the pipe/threading model.
reference:
---

**Issue:** Immediately after a `chatbot-ctl.sh` restart, the very first real message sent (which adopted the freshly-warmed standby process — see `_StandbyPool`) produced a correct assistant reply but its `usage` object came back with every field present and set to `0` (`input_tokens/output_tokens/thinking_tokens/cache_read_tokens/total_tokens` all `0`), and its brain directory (`~/.gemini/antigravity-cli/brain/<cid>/`) had no `.system_generated/logs/transcript_full.jsonl` at all — completely empty. Two subsequent test messages (one forcing a cold spawn via a non-default model, one going through the standby path again) both returned correct, non-zero usage. Not reproduced on retry, so this looks like a race specific to the very first standby adopted right after server startup, not a general standby-adoption bug — the standby-adoption code path itself was verified correct via two later successful runs.

**Suggested improvement:** If this recurs, check whether it correlates with the maintenance loop's very first `ensure_warm()` call overlapping with something else in server startup (e.g. the doctor's post-restart `probe_message` also spawning/claiming a process around the same moment — the restart's own probe and the standby maintenance loop both fire within seconds of each other at startup). Consider logging `agy`'s raw stdout for the standby process from the moment it's spawned (buffered in the pipe until adoption per the `_StandbyPool` docstring) rather than only from adoption onward, to rule out an early partial write being silently dropped.

**Principle:** A pre-warmed/pooled resource that's adopted instead of freshly created can carry state (or lack of state, like a not-yet-fully-initialized handshake) from a different moment in time than a fresh spawn would — bugs that only appear on the *first* pooled resource right after a cold service start are a distinct class from bugs that appear on every pooled resource, and need to be tested specifically at that boundary (right after restart), not just via repeated steady-state adoption.
