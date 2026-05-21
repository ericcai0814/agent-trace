# agent-trace

跨 agent 的 telemetry pipeline——把 AI coding agent 的 transcript 抽成正規化事件流，做 skill/agent 使用量分析、dead-skill 偵測、行為 eval baseline。

## How this was built

agent-trace is built with a spec-driven workflow: I designed the telemetry concept, event schema, and CLI surface, then generated the Python implementation via Claude Code and reviewed/integrated it before shipping.

### What I authored vs what AI implemented

| Authored by me | Implemented via Claude Code |
|---|---|
| Cross-agent telemetry concept & motivation (the "Why") | Python pipeline implementation |
| Normalized event schema across Claude Code / Gemini CLI / Codex | JSONL streaming parser & ingest logic |
| Skill/agent usage metrics taxonomy (`usage` / `channels` / `dead-skills`) | CLI scaffolding & command structure |
| Adapter abstraction for multi-agent transcript ingestion | Test fixtures |
| Phase 1 scope & roadmap (`Status` section below) | Backfill flow & SessionEnd hook design (Phase 2 plan) |

If you spot an issue, please open one — I read and respond to all issues, including ones in the AI-generated code paths.

## Status

✅ Phase 2 — Claude Code adapter、CLI、SessionEnd hook 自動串接全部完成。下一階段是第二個 adapter (Gemini CLI / Codex,Phase 3,條件性)。

## Quick start

```bash
# 用 uv tool install (推薦) 或 pipx,讓 agent-trace 全域可用
uv tool install git+https://github.com/ericcai0814/agent-trace.git

# 一次性 backfill 既有 transcripts → ~/.claude/metrics.jsonl
agent-trace backfill --adapter claude-code

# 註冊 SessionEnd hook,之後每次 session 結束自動 ingest
agent-trace install-hook --adapter claude-code

# 三種診斷視圖 (不需要 --adapter,直接讀正規化資料)
agent-trace reports channels       # auto vs slash 比例
agent-trace reports usage          # 每個 skill 的 channel 拆解
agent-trace reports dead-skills    # 從未被觸發的 skill
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

- [x] Phase 0 — `NormalizedEvent` schema 與 ABI 凍結
- [x] Phase 1 — Claude Code adapter + backfill + aggregator CLI
- [x] Phase 2 — SessionEnd hook 自動 ingest (`agent-trace install-hook`)
- [ ] Phase 3 — Gemini CLI / Codex adapter（等實際使用時再寫）

## Design

完整設計與決策紀錄見 [`docs/PLANNING.md`](docs/PLANNING.md)。

## License

MIT
