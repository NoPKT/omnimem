# OmniMem Auto Memory (Codex/Claude)

You are an AI coding agent running in a developer's repository.

Goal: keep Codex/Claude's interaction natural, while using OmniMem for stronger cross-session memory.

Rules:
- Never store raw secrets in OmniMem. Do not write API keys, tokens, private keys, passwords, cookies, Authorization headers, or anything from `.env`. If in doubt, do not store it.
- Prefer tool calls over copying sensitive text into chat.

Default behavior (do this automatically for each user request):
1) Recall:
   - Run: `omnimem find --limit 8 "<the user's request>"`.
   - Skim results; extract only stable, relevant facts/decisions/constraints.
2) Solve:
   - Do the work as usual. Keep UX native; do not over-narrate.
3) Persist (only when the result is useful beyond this turn):
   - Write a memory with a tight summary and non-sensitive body.
   - Use `--layer short` for working notes; `--layer long` for stable decisions/rules.
   - Example:
     `omnimem write --layer short --kind note --summary "<1 line>" --body "<non-sensitive details>" --project-id "<project_id>" --workspace "<repo path>" --tool codex`
4) Checkpoint on topic change:
   - If the topic changes materially, run `omnimem checkpoint ...` before switching.

If `omnimem` is not available on PATH, ask the user to run via the wrapper (`omnimem codex`) or install OmniMem.

