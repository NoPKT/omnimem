# AI Agent Context/Quota/Memory Research Notes (2026-02-12)

This note tracks recurring pain points for Codex/Claude-style agent workflows and maps them to OmniMem implementation choices.

## Pain points observed in primary sources

1. Long-context quality is not uniform across position.
Top/middle/bottom placement materially affects recall quality in long prompts.
Source: "Lost in the Middle" (TACL 2024): https://aclanthology.org/2024.tacl-1.9/

2. Prompt/token pressure and rate limits are operational constraints.
Both OpenAI and Anthropic document explicit rate-limit behavior and recommend retry/backoff patterns.
Sources:
- OpenAI rate limits: https://platform.openai.com/docs/guides/rate-limits
- Anthropic rate limits: https://docs.anthropic.com/en/api/rate-limits
- Anthropic errors (429 guidance): https://docs.anthropic.com/en/api/errors

3. Prompt caching depends on stable, repeated prefixes.
If prefixes change on every turn, cache efficiency drops.
Sources:
- Anthropic prompt caching: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- OpenAI prompt caching: https://platform.openai.com/docs/guides/prompt-caching

4. Long context requires explicit structuring tactics.
Chunking, ordering, and explicit retrieval structure are recommended rather than "dump everything".
Source: Anthropic long context tips: https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/long-context-tips

5. Stateful memory across turns is needed beyond single-window context.
Virtual-context / external-memory patterns are an established direction.
Source: MemGPT (arXiv): https://arxiv.org/abs/2310.08560

6. Output budgeting should be explicit, not open-ended.
Provider guidance emphasizes reducing unnecessary output tokens and shaping response length for latency/cost/rate stability.
Sources:
- OpenAI latency optimization: https://platform.openai.com/docs/guides/latency-optimization
- Anthropic token counting: https://docs.anthropic.com/en/docs/build-with-claude/token-counting

## OmniMem mapping

1. Quota-aware context shaping:
- `--context-profile` and `--quota-mode` derive effective token budget/retrieve width.
- `--quota-mode auto` maps prompt size to `normal/low/critical` automatically.

2. Stable-prefix injection:
- memory context header is stable by default (runtime timestamp removed) to improve prompt-cache hit rates.

3. Delta-first context:
- keep incremental memory recall and carry-over queue to reduce repeated token payload.

4. Operational transparency:
- `--show-context-plan` prints effective budget/retrieve/delta choices before tool launch.

5. Runtime output-size feedback:
- Agent runtime hints now estimate observed output token size and suggest a tighter `max_output_tokens` target.
- Under transient retry pressure plus large outputs, hints recommend concise-output patterns to avoid quota spikes.
