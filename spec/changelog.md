# Schema Changelog

## v0.1.1 (2026-02-09)

- Added daemon state API schema: `spec/daemon-state.schema.json`.
- Added daemon status fields:
  - `schema_version`
  - retry settings (`retry_max_attempts`, `retry_initial_backoff`, `retry_max_backoff`)
  - runtime counters (`cycles`, `success_count`, `failure_count`)
  - timestamps (`last_run_at`, `last_success_at`, `last_failure_at`)
  - classified failure fields (`last_error_kind`, `last_error`)
  - remediation field (`remediation_hint`)
- Introduced failure classification kinds for sync flows:
  - `auth`
  - `network`
  - `conflict`
  - `unknown`

## v0.1.0 (2026-02-08)

- Initial `MemoryEnvelope` and `MemoryEvent` schemas.
- Layered memory model and event taxonomy.
- Credential reference constraints (no plaintext secrets).
- Added `signals` fields:
  - `importance_score`
  - `confidence_score`
  - `stability_score`
  - `reuse_count`
  - `volatility_score`
- Added corresponding signal columns and indexes in SQLite `memories` table.
