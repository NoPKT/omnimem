# Startup Guide QA Checklist

Language: [English](qa-startup-guide.md) | [简体中文](qa-startup-guide.zh-CN.md)

Use this checklist for a real first-time user run:

1. Prepare clean environment
- Use a fresh `OMNIMEM_HOME`.
- Ensure `sync.github.remote_url` is empty in config.
- Run in interactive terminal (not CI).

2. Path A: fully ready auto-run
- Preconditions: OAuth client id available and provider CLI installed + logged in.
- Run: `omnimem start`.
- Expect: startup guide auto-runs without prompt and attempts broker deploy.

3. Path B: missing client id
- Preconditions: no OAuth client id in env/config.
- Run: `omnimem start`.
- Expect: one inline prompt for client id, then flow continues.

4. Path C: provider installed but not logged in
- Preconditions: provider CLI installed, not authenticated.
- Run: `omnimem start`.
- Expect: login hint prompt, optional command execution, then auto flow continues.

5. Path D: provider CLI missing
- Preconditions: recommended provider CLI not installed.
- Run: `omnimem start`.
- Expect: install hint + wizard fallback prompt; startup must not crash.

6. URL write-back behavior
- On successful deploy output with URL, check config:
  - `sync.github.oauth.broker_url` updated automatically.
- If URL cannot be detected, ensure startup keeps running and prints manual follow-up hint.

7. Disable behavior
- At prompt, enter `never`.
- Re-run `omnimem start`.
- Expect: no further startup guide prompts (`setup.startup_guide_disabled=true`).
