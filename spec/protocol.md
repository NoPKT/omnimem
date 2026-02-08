# OmniMem Protocol v0.1.0

## 1. Versioning

- Protocol version: `0.1.0`
- Semantic versioning rules:
  - `MAJOR`: breaking model changes
  - `MINOR`: backward-compatible additions
  - `PATCH`: fixes and clarifications

## 2. Memory Envelope

Required fields:

- `id`
- `schema_version`
- `created_at`
- `updated_at`
- `layer` (`instant|short|long|archive`)
- `kind` (`note|decision|task|checkpoint|summary|evidence`)
- `summary`
- `body_md_path`
- `tags`
- `refs`
- `signals`
- `cred_refs`
- `source`
- `scope`
- `integrity`

`signals` fields:

- `importance_score` [0,1]
- `confidence_score` [0,1]
- `stability_score` [0,1]
- `reuse_count` >= 0
- `volatility_score` [0,1]

Constraints:

- `cred_refs` must never contain plaintext secrets.
- `body_md_path` must be repo-relative.
- `integrity.content_sha256` must match markdown body hash.

## 3. JSONL Event Model

One event per line. Event types:

- `memory.write`
- `memory.update`
- `memory.checkpoint`
- `memory.promote`
- `memory.verify`
- `memory.sync`

Required fields:

- `event_id`
- `event_type`
- `event_time`
- `memory_id`
- `payload`

## 4. SQLite Model

- `memories`: envelope metadata and signals
- `memory_refs`: reference graph
- `memory_events`: event log
- `memories_fts`: FTS5 for summary/body text

SQLite is rebuildable from Markdown + JSONL.

## 5. Audit and Migration

- Track schema changes in `spec/changelog.md`.
- Keep event logs append-only.
- Provide migration tooling for future protocol updates.
