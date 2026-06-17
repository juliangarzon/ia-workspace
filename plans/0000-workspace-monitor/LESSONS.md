
## T7 — Claude data format confirmation (2026-06-17)

### stats-cache.json (version: 2)
Keys: `version`, `lastComputedDate`, `dailyActivity`, `dailyModelTokens`, `modelUsage`
- `dailyActivity[n]`: `{date, messageCount, sessionCount, toolCallCount}` — NO token counts
- `dailyModelTokens[n]`: `{date, tokensByModel: {model_id: total_tokens}}` — total only, no input/output split
- Token breakdown (input/output/cache) only available in JSONL transcripts

### sessions/<pid>.json
Fields: `pid`, `sessionId`, `cwd`, `startedAt` (unix ms), `procStart`, `version`, `peerProtocol`, `kind`, `entrypoint`
- NO `lastEventAt` — must derive from JSONL file mtime or last record timestamp
- `kind`: "interactive" | "noninteractive" (likely)

### JSONL transcript records (type == "assistant")
- `message.usage.input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`
- `message.usage.cache_creation.ephemeral_5m_input_tokens`, `ephemeral_1h_input_tokens` (tiered, present in newer)
- `message.usage.service_tier`: "standard" | "fast"
- `costUSD`: float | None — CAN BE NULL even on recent records. Pricing table fallback required.
- `isSidechain`: bool — True for subagent/tool background calls
- `gitBranch`: str | None
- `timestamp`: ISO8601 UTC string e.g. "2026-05-28T15:25:53.965Z"
- `sessionId`: UUID string

### scheduled-tasks/<name>/SKILL.md
YAML frontmatter with `name` and `description`. No cron schedule embedded — tasks are triggered externally. `schedule` and `next_run` will always be `None` for now.
