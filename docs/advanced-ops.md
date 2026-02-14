# Advanced Operations (Maintainers)

Language: [English](advanced-ops.md) | [简体中文](advanced-ops.zh-CN.md)

This page contains maintainer-focused commands that are intentionally kept out of the main user onboarding path.

## Advanced Agent Controls

```bash
omnimem codex --project-id <project_id> --drift-threshold 0.62 --cwd /path/to/project
omnimem claude --project-id <project_id> --drift-threshold 0.62 --cwd /path/to/project
omnimem codex --smart --context-budget-tokens 420
omnimem codex --smart --no-delta-context
omnimem codex --context-profile balanced --quota-mode normal --show-context-plan
omnimem codex --context-profile low_quota --quota-mode critical --show-context-plan
omnimem claude --context-profile deep_research --quota-mode low --show-context-plan
omnimem codex --context-profile balanced --quota-mode auto --show-context-plan
omnimem context-plan --prompt "refactor sync daemon retry policy" --context-profile balanced --quota-mode auto
omnimem context-plan --from-runtime --tool codex --project-id OM --context-profile balanced --quota-mode auto
omnimem agent run --tool codex --project-id OM --prompt "..." --retry-max-attempts 4 --retry-initial-backoff 1.5 --retry-max-backoff 12
npm run ci:watch
bash scripts/ci_watch.sh --workflow ci.yml --branch main --max-wait-min 45
```

Context policy flags:

- `--context-profile`: `balanced | low_quota | deep_research | high_throughput`
- `--quota-mode`: `normal | low | critical | auto`
- `--show-context-plan`: print effective budget/retrieve/delta plan before launch
- `omnimem context-plan` now returns `decision_reason` to explain why auto mode selected current quota tier.
- `omnimem context-plan --from-runtime` also returns `recent_context_utilization_used` for utilization-aware auto decisions.
- Auto mode can also tighten quota based on recent transient failures and recent context utilization from local runtime history.

Notes:

- Context prefix is stable by default (timestamp removed) to improve provider prompt-cache hit rate.
- `critical` quota mode aggressively shrinks context and retrieval breadth to reduce token pressure.
- Agent/oneshot paths include transient failure retry (`429/overloaded/timeout/5xx`) with exponential backoff.
- If tool error text includes a `retry-after` hint, OmniMem backoff uses it as a lower bound.
- `omnimem agent run` output now includes `tool_attempts`, `tool_retried`, `tool_transient_failures` for retry observability.
- `omnimem agent run` also includes context efficiency fields: `context_budget_tokens`, `context_estimated_tokens`, `context_utilization`, and core/expand selection counts.
- `context_pressure` and `context_hint` provide actionable interpretation (`low|balanced|high`) for tuning profile/quota/retrieve settings.
- `runtime_hints` adds concise next-step suggestions derived from retries, pressure, and inferred route.
- `runtime_hints` also estimates observed output token size and suggests a tighter `max_output_tokens` target.

For safer governance rollout in WebUI:

- `webui.approval_required=true`
- `webui.maintenance_preview_only_until=<ISO-8601 UTC>`

## Frontier Memory Operations

```bash
omnimem raptor --project-id OM
omnimem enhance --project-id OM
omnimem profile --project-id OM
omnimem profile-drift --project-id OM --recent-days 14 --baseline-days 120
omnimem core-set --project-id OM --name persona --body "Be concise, explicit, and test-first." --priority 80
omnimem core-set --project-id OM --name style-a --topic style --body "Use short bullets." --priority 60
omnimem core-set --project-id OM --name style-b --topic style --body "Use numbered technical lists." --priority 90
omnimem core-set --project-id OM --name temporary-guardrail --body "Prefer safe default ops." --ttl-days 7
omnimem core-merge-suggest --project-id OM --min-conflicts 2
omnimem core-merge-suggest --project-id OM --min-conflicts 2 --apply
omnimem core-merge-suggest --project-id OM --apply --loser-action deprioritize --min-apply-quality 0.25
omnimem core-merge-suggest --project-id OM --merge-mode synthesize --max-merged-lines 6
omnimem core-merge-suggest --project-id OM --merge-mode semantic --max-merged-lines 6
omnimem core-list --project-id OM
omnimem core-list --project-id OM --include-expired
omnimem core-get --project-id OM --name persona
omnimem retrieve "workflow guide" --project-id OM --drift-aware --drift-weight 0.4 --explain
omnimem retrieve "workflow guide" --project-id OM --include-core-blocks --core-block-limit 2 --explain
omnimem retrieve "workflow guide" --project-id OM --include-core-blocks --core-merge-by-topic --explain
omnimem ingest --type url "https://example.com/doc?token=***"
omnimem ingest --type file ./docs/notes.md
omnimem ingest --type file ./docs/design.md --chunk-mode heading --max-chunks 12
omnimem ingest --type text --text "..." --chunk-mode fixed --chunk-chars 1800
omnimem feedback --id <memory_id> --feedback positive --note "high value"
omnimem sync --mode github-push --sync-layers long,archive --no-sync-include-jsonl
omnimem prune --project-id OM --days 45 --layers instant,short --keep-kinds decision,checkpoint
omnimem prune --project-id OM --days 45 --layers instant,short --keep-kinds decision,checkpoint --apply
```

## Evaluation and Tuning

Offline LoCoMo-style retrieval eval:

```bash
python3 scripts/eval_locomo_style.py --dataset eval/locomo_style.sample.jsonl
```

Retrieval A/B eval:

```bash
python3 scripts/eval_retrieval.py --dataset eval/retrieval_dataset_om.json --with-drift-ab --drift-weight 0.4
```

Core merge mode eval:

```bash
python3 scripts/eval_core_merge.py --project-id OM --modes concat,synthesize,semantic --max-merged-lines 6
```

Tune `core-merge-suggest` defaults:

```bash
python3 scripts/tune_core_merge_from_eval.py --report eval/core_merge_report_om.json
python3 scripts/tune_core_merge_from_eval.py --report eval/core_merge_report_om.json --dry-run
```

Build retrieval eval dataset:

```bash
PYTHONPATH=. python3 scripts/build_eval_dataset.py --project-id OM --limit 60 --out eval/retrieval_dataset_om.json
```

Run retrieval quality evaluation:

```bash
PYTHONPATH=. python3 scripts/eval_retrieval.py --dataset eval/retrieval_dataset_om.json --with-drift-ab --drift-weight 0.4 --out eval/retrieval_report_om.json
```

Distill one session:

```bash
PYTHONPATH=. python3 -m omnimem.cli distill --project-id OM --session-id <session_id>
PYTHONPATH=. python3 -m omnimem.cli distill --project-id OM --session-id <session_id> --apply
```

Profile-aware retrieval:

```bash
PYTHONPATH=. python3 -m omnimem.cli retrieve "workflow guide" --project-id OM --profile-aware --profile-weight 0.5 --explain
```

Tune adaptive governance quantiles:

```bash
PYTHONPATH=. python3 scripts/tune_governance_from_eval.py --report eval/retrieval_report_om.json
```

Enable temporary preview-only governance:

```bash
PYTHONPATH=. python3 scripts/enable_governance_preview.py --days 7
```
