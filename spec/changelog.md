# Schema Changelog

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
