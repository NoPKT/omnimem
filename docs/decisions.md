# Key Decisions

## D1: Dual-view storage

Use Markdown for high-value readable knowledge, JSONL/SQLite for high-volume operational memory.

## D2: Rebuildable index

SQLite is a local acceleration layer and can be rebuilt from Markdown + JSONL.

## D3: CLI-first portability

Core behavior is exposed via CLI, avoiding dependence on one MCP ecosystem.

## D4: Secret-safe memory

Never persist plaintext secrets in memory content. Only store credential references.

## D5: Minimal project integration

Attach/remove with 2-4 small files to keep business code untouched.

## D6: WebUI as management layer

WebUI improves visibility and control but is not the source of truth.
