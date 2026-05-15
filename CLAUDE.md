# agent-trace — Project Instructions

## What this is

Cross-agent telemetry pipeline. Parses transcripts from AI coding agents into a normalized event stream for usage analysis, dead-skill detection, and behavior eval baselines.

Currently Phase 0 (schema design + planning). See [`docs/PLANNING.md`](docs/PLANNING.md) for the full design, decisions, and phase plan.

## Structure

```
agent_trace/
├── core/                   # Agent-agnostic pipeline
│   ├── events.py           #   NormalizedEvent dataclass (the ABI)
│   ├── storage.py          #   metrics.jsonl read/write
│   └── aggregate.py        #   usage table, dead-skill diff, channel breakdown
├── adapters/
│   ├── base.py             #   abstract Adapter interface
│   └── claude_code.py      #   Phase 1 concrete impl
└── cli.py                  # agent-trace ingest | report | backfill

docs/
├── PLANNING.md             # design + decisions
├── adr/                    # future ADRs
└── agents/                 # per-repo dev config (gitignored)

hooks/<agent>/              # sample SessionEnd snippets per agent
tests/fixtures/<agent>/     # sample transcripts per agent
```

## Conventions

- Each adapter emits `core.events.NormalizedEvent` — same shape regardless of source agent
- Aggregators consume `NormalizedEvent` only, never adapter-specific types
- `core/` is the public contract; adapters can evolve independently
- Dual-channel skill detection: agents must distinguish `auto` (tool call) from `slash` (user-typed `<command-name>`)

## Boundaries

- **Always:** keep `core/` agent-agnostic. If adapter logic creeps in, refactor.
- **Never:** add agent-specific logic to `core/aggregate.py` or `core/storage.py`.
- **Never:** commit `metrics.jsonl` — user-local accumulated data, lives at `~/.claude/metrics.jsonl`.
- **Never:** commit `docs/agents/*.md` (except this directory's own README) — per-repo dev config from mattpocock skills.

## Commits

Use Conventional Commits. zh-TW or English subject lines both fine for this project (cross-language contributors expected).
