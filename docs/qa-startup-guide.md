# Startup Guide QA Checklist

Language: [English](qa-startup-guide.md) | [简体中文](qa-startup-guide.zh-CN.md)

Use this checklist to validate first-time startup behavior for real users.

## Executable Checklist

1. Prepare environment
   - use a fresh `OMNIMEM_HOME`
   - ensure `sync.github.remote_url` is empty
   - run in interactive terminal (not CI)

2. Path A: fully ready auto-run
   - preconditions: OAuth client id available, provider CLI installed and logged in
   - run: `omnimem start`
   - expect: startup guide auto-runs without extra prompt

3. Path B: missing client id
   - preconditions: no OAuth client id in env/config
   - run: `omnimem start`
   - expect: one inline prompt for client id, then flow continues automatically

4. Path C: provider installed but not logged in
   - preconditions: provider CLI exists but not authenticated
   - run: `omnimem start`
   - expect: login hint/command prompt, then flow resumes

5. Path D: provider CLI missing
   - preconditions: recommended provider CLI not installed
   - run: `omnimem start`
   - expect: install hint + wizard fallback, no crash

6. URL write-back
   - when deploy output contains URL, verify `sync.github.oauth.broker_url` is auto-written
   - if URL cannot be detected, startup should continue and print manual follow-up command

7. Disable behavior
   - enter `never` at startup guide prompt
   - re-run `omnimem start`
   - expect no further startup guide prompts (`setup.startup_guide_disabled=true`)

## Failure Triage Table

| Symptom | Likely cause | Action |
|---|---|---|
| `startup guide did not run` | startup guide disabled or non-interactive shell | check `setup.startup_guide_disabled`; ensure interactive terminal |
| `provider CLI not found` | provider tool missing | install suggested CLI (`wrangler`/`vercel`/`railway`/`flyctl`) and retry |
| `provider not authenticated` | CLI exists but no login session | run provider login command, then `omnimem start` again |
| `broker deployed but URL not written` | deploy output URL parse failed | manually set `sync.github.oauth.broker_url` in config |
| `OAuth login keeps pending` | device flow not completed in browser | complete verification URI flow, then click/poll again |
| `startup aborted` | unexpected runtime/tooling failure | run `omnimem doctor`, then retry with `omnimem oauth-broker doctor` |

## Quick Verification Commands

```bash
omnimem doctor
omnimem oauth-broker doctor
```
