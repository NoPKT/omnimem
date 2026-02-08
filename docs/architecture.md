# OmniMem Architecture

## Layered memory model

Memory is layered by value signals, not by time only:

- `instant`: noisy, short-lived trial context.
- `short`: validated task context and near-term reuse.
- `long`: high-value, repeated, stable knowledge.
- `archive`: cold historical snapshots and references.

Promotion/demotion signals:

- `importance_score`
- `confidence_score`
- `stability_score`
- `reuse_count`
- `volatility_score`

## Storage model

- Markdown: human-readable source for important memory.
- JSONL: append-only audit/event source.
- SQLite FTS: local query acceleration, rebuildable.

## Sync model

- Source of truth syncs via Git: Markdown + JSONL + spec/docs.
- SQLite does not need binary sync; rebuild locally.

## Tool model

- Core interface is CLI, not a single MCP implementation.
- Optional adapters: GitHub, Notion, 1Password refs, R2.
