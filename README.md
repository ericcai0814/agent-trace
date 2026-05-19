# agent-trace

跨 agent 的 telemetry pipeline——把 AI coding agent 的 transcript 抽成正規化事件流，做 skill/agent 使用量分析、dead-skill 偵測、行為 eval baseline。

## Status

🚧 Phase 1 — Claude Code adapter 與 CLI 已可運作。SessionEnd hook 自動串接屬 Phase 2。

## Quick start

```bash
git clone <repo> && cd agent-trace
python3.13 -m venv .venv
.venv/bin/pip install -e .

# Backfill 既有 transcripts → ~/.claude/metrics.jsonl
agent-trace backfill --adapter claude-code

# 看 skill 使用表（按 channel 拆開 auto vs slash）
agent-trace reports usage

# 看 channel 分布總計
agent-trace reports channels

# 看哪些 skill 從沒被觸發過
agent-trace reports dead-skills

# 單檔 ingest，可直接接 SessionEnd hook
agent-trace ingest --adapter claude-code <path-to-transcript.jsonl>
```

## Why

當你的開發流程橫跨 Claude Code、Gemini CLI、Codex 多個 agent 工具，每個工具都有自己的 transcript 格式、各自的「skill」概念、各自的 hook 機制——但**沒有統一視角**告訴你：

- 哪些 skill 是死的？description 寫了沒人用？
- skill 跟 subagent 怎麼配合？哪些組合常見？
- 跨 agent 的工作模式有沒有遷移成本？

`agent-trace` 是回答這些問題的工具。

## How it works

```
transcript.jsonl
    ↓ (adapter.parse)
NormalizedEvent stream
    ↓ (aggregate.session_record)
per-session dict
    ↓ (storage.append)
~/.claude/metrics.jsonl
    ↓ (storage.read_all → aggregate.usage_table/dead_skills/channel_breakdown)
report 表格
```

## Roadmap

- [ ] Phase 0 — `NormalizedEvent` schema 與 ABI 凍結
- [ ] Phase 1 — Claude Code adapter + backfill + aggregator CLI
- [ ] Phase 2 — SessionEnd hook 自動 ingest
- [ ] Phase 3 — Gemini CLI / Codex adapter（等實際使用時再寫）

## Design

完整設計與決策紀錄見 [`docs/PLANNING.md`](docs/PLANNING.md)。

## License

MIT
