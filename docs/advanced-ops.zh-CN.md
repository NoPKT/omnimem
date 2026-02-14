# 高级运维与评测（维护者）

English: [advanced-ops.md](advanced-ops.md)

本页汇总维护者/研发向命令，避免主 README 对普通用户造成干扰。

## Agent 高级控制

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

上下文策略参数：

- `--context-profile`: `balanced | low_quota | deep_research | high_throughput`
- `--quota-mode`: `normal | low | critical | auto`
- `--show-context-plan`: 启动前打印实际生效的上下文预算/检索/增量策略
- `omnimem context-plan` 现会返回 `decision_reason`，解释 auto 模式为何进入当前配额档位。
- `omnimem context-plan --from-runtime` 还会返回 `recent_context_utilization_used`，用于利用率感知的 auto 决策。
- auto 模式还会结合本地近期瞬时失败历史与上下文利用率自动收紧配额档位。

说明：

- 默认使用稳定上下文前缀（移除时间戳）以提升 provider 侧 prompt cache 命中率。
- `critical` 配额模式会更激进地收缩上下文和检索宽度，降低 token 压力。
- 在 agent/oneshot 路径下，针对瞬时失败（429/overloaded/timeout/5xx）已启用指数退避重试。
- 若错误文本包含 `retry-after` 提示，OmniMem 会将其作为退避等待下限。
- `omnimem agent run` 输出已包含 `tool_attempts`、`tool_retried`、`tool_transient_failures`，便于观察重试行为。
- `omnimem agent run` 还会输出上下文效率字段：`context_budget_tokens`、`context_estimated_tokens`、`context_utilization` 及 core/expand 选取计数。
- `context_pressure` 与 `context_hint` 会给出可操作解释（`low|balanced|high`），用于调节 profile/quota/retrieve 参数。
- `runtime_hints` 会基于重试、压力与路由推断给出简短下一步建议。
- `runtime_hints` 还会估算实际输出 token 规模，并给出更收敛的 `max_output_tokens` 建议值。

WebUI 治理安全发布建议：

- `webui.approval_required=true`
- `webui.maintenance_preview_only_until=<ISO-8601 UTC>`

## 前沿记忆操作

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

## 评测与调参

离线 LoCoMo 风格检索评测：

```bash
python3 scripts/eval_locomo_style.py --dataset eval/locomo_style.sample.jsonl
```

检索 A/B 评测：

```bash
python3 scripts/eval_retrieval.py --dataset eval/retrieval_dataset_om.json --with-drift-ab --drift-weight 0.4
```

Core merge 模式评测：

```bash
python3 scripts/eval_core_merge.py --project-id OM --modes concat,synthesize,semantic --max-merged-lines 6
```

调优 `core-merge-suggest` 默认值：

```bash
python3 scripts/tune_core_merge_from_eval.py --report eval/core_merge_report_om.json
python3 scripts/tune_core_merge_from_eval.py --report eval/core_merge_report_om.json --dry-run
```

构建检索评测数据集：

```bash
PYTHONPATH=. python3 scripts/build_eval_dataset.py --project-id OM --limit 60 --out eval/retrieval_dataset_om.json
```

运行检索质量评测：

```bash
PYTHONPATH=. python3 scripts/eval_retrieval.py --dataset eval/retrieval_dataset_om.json --with-drift-ab --drift-weight 0.4 --out eval/retrieval_report_om.json
```

会话蒸馏：

```bash
PYTHONPATH=. python3 -m omnimem.cli distill --project-id OM --session-id <session_id>
PYTHONPATH=. python3 -m omnimem.cli distill --project-id OM --session-id <session_id> --apply
```

Profile-aware 检索：

```bash
PYTHONPATH=. python3 -m omnimem.cli retrieve "workflow guide" --project-id OM --profile-aware --profile-weight 0.5 --explain
```

根据评测报告调优治理分位：

```bash
PYTHONPATH=. python3 scripts/tune_governance_from_eval.py --report eval/retrieval_report_om.json
```

开启临时仅预览治理窗口：

```bash
PYTHONPATH=. python3 scripts/enable_governance_preview.py --days 7
```
