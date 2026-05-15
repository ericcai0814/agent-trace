# agent-trace

跨 agent 的 telemetry pipeline——把 AI coding agent 的 transcript 抽成正規化事件流，做 skill/agent 使用量分析、dead-skill 偵測、行為 eval baseline。

## Status

🚧 早期規劃中。Phase 0：schema 設計與 Claude Code adapter。

## Why

當你的開發流程橫跨 Claude Code、Gemini CLI、Codex 多個 agent 工具，每個工具都有自己的 transcript 格式、各自的「skill」概念、各自的 hook 機制——但**沒有統一視角**告訴你：

- 哪些 skill 是死的？description 寫了沒人用？
- skill 跟 subagent 怎麼配合？哪些組合常見？
- 跨 agent 的工作模式有沒有遷移成本？

`agent-trace` 是回答這些問題的工具。

## Roadmap

- [ ] Phase 0 — `NormalizedEvent` schema 與 ABI 凍結
- [ ] Phase 1 — Claude Code adapter + backfill + aggregator CLI
- [ ] Phase 2 — SessionEnd hook 自動 ingest
- [ ] Phase 3 — Gemini CLI / Codex adapter（等實際使用時再寫）

## Design

完整設計與決策紀錄見 [`docs/PLANNING.md`](docs/PLANNING.md)。

## License

MIT
