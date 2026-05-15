# agent-trace — Design & Decisions

> **Status:** Phase 0 — schema design and planning. No business code yet.
> **Last updated:** 2026-05-15

## Problem

When development spans multiple AI coding agents (Claude Code, Gemini CLI, Codex), each tool has its own transcript format, "skill" concept, and hook mechanism — but there's no unified way to answer:

- Which skills are dead? Description written but never triggered?
- How do skills and subagents compose? Which combinations recur?
- Are there cross-agent migration costs in working patterns?
- For any given skill, what fraction of invocations is auto-triggered (via description routing) vs forced (via slash command)?

Existing per-tool dashboards answer subsets of this. None unify across tools, and at least one in-house extractor was found to silently undercount invocations by ~60% by observing only one of two distinct trigger channels.

## Goals

- Parse transcripts from multiple AI coding agents into one normalized event stream
- Detect skill/command usage across **two channels**: auto-trigger (via tool call) and user-typed (via slash command expansion)
- Surface dead-skill detection (whitelist vs invoked diff)
- Produce per-session metrics suitable for aggregation and behavior eval baselines
- Pluggable adapter interface so new agents can be added without touching `core/`

## Non-goals

- Real-time streaming dashboard (per-session grain is enough)
- LLM-based eval of agent output quality (downstream concern; agent-trace is the data layer)
- Replace existing per-tool session loggers (coexist, don't displace)
- Cover non-coding agents (chat-only, multi-modal applications)

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                       Agent Transcripts                            │
│   Claude Code JSONL  │  Gemini CLI logs  │  Codex transcripts      │
└──────┬─────────────────────┬────────────────────┬──────────────────┘
       │                     │                    │
       ▼                     ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ claude_code  │    │  gemini_cli  │    │    codex     │
│   adapter    │    │   adapter    │    │   adapter    │
│  (Phase 1)   │    │  (Phase 3)   │    │  (Phase 3)   │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           ▼
              ┌─────────────────────────┐
              │   NormalizedEvent       │
              │   (agent-agnostic ABI)  │
              └────────────┬────────────┘
                           ▼
              ┌─────────────────────────┐
              │  Storage                │
              │  ~/.claude/metrics.jsonl│
              │  (one record/session)   │
              └────────────┬────────────┘
                           ▼
              ┌─────────────────────────┐
              │  Aggregator + Reports   │
              │  • usage table          │
              │  • dead-skill diff      │
              │  • channel breakdown    │
              └─────────────────────────┘
```

---

## Key Decisions

Each decision below follows the format: **Context** (why this needs deciding) → **Decision** (what we chose) → **Why** (the reasoning) → **Alternative considered** (what we rejected and why) → **Trade-off accepted** (what this costs).

### D1: Standalone repo, not a Claude Code plugin

**Context.** The original telemetry mechanism lived inside a single agent's config dir (a SessionEnd hook plus a Python extractor). Extending coverage to Gemini CLI and Codex requires a home that isn't tied to one agent's plugin format.

**Decision.** Build as a standalone pip-installable Python package in its own public repo.

**Why.** A plugin tied to one agent cannot observe other agents. Cross-agent normalization is the entire reason for this project to exist as a separate codebase.

**Alternative considered.** Distribute as a Claude Code plugin and ship per-agent shims internally. Rejected — Claude plugin format doesn't load in Gemini or Codex, so we would ship a non-plugin payload regardless. The plugin wrapper would add packaging complexity with no portability benefit.

**Trade-off accepted.** Users install via `pip install agent-trace` and wire hooks manually per agent (sample snippets in `hooks/`). No one-click marketplace install.

---

### D2: Pluggable adapter interface day 1, only Claude Code implemented

**Context.** The author currently does ~99% of work in Claude Code, with Gemini CLI and Codex on the roadmap. We must choose how much abstraction to build before there's a second adapter.

**Decision.** Define the abstract `Adapter` interface in `core/` from the start, but ship only `adapters/claude_code.py` in Phase 1. Adapters for Gemini and Codex are Phase 3 work, gated on actual usage (see Q2).

**Why.** Interface design is cheap when there's one implementation, and it forces clean separation between agent-specific and agent-agnostic concerns. Implementing three adapters speculatively violates YAGNI.

**Alternative considered.**
- *Monolithic Claude-only design now, refactor on the day of need.* Rejected — the refactor when a second agent arrives would be much more expensive than getting the interface right today, because aggregator code would already be coupled to Claude-specific types.
- *Build all three adapters now.* Rejected — the schema would not be pressure-tested against a real second adapter, so it would freeze a wrong shape.

**Trade-off accepted.** The interface might still be wrong; we accept that the schema is unstable until the second concrete adapter lands. See Q1 for the stability commitment criterion.

---

### D3: `NormalizedEvent` as the agent-agnostic ABI

**Context.** Aggregators and reports must not depend on agent-specific event shapes. Each agent has different concepts: Claude Code has explicit `Skill` and `Agent` tool types and `<command-name>` tags; Gemini has native skill resolution; Codex has multi-agent orchestration. These must map onto one schema.

**Decision.** A single dataclass with a discriminated union via `event_type`:

```python
@dataclass
class NormalizedEvent:
    ts: datetime
    agent: Literal["claude-code", "gemini-cli", "codex"]
    session_id: str
    project: str | None
    event_type: Literal["tool_call", "skill_invoke", "subagent_spawn", "user_prompt"]

    tool_name: str | None
    skill_name: str | None
    skill_channel: Literal["auto", "slash", "hook"] | None
    subagent_name: str | None
    user_text: str | None  # truncated

    raw: dict  # adapter-specific source blob, retained for debug / future fields
```

**Why.** A flat dataclass with optional fields is simpler than a polymorphic class hierarchy. The `raw` escape hatch preserves source fidelity when normalization loses information, so future enhancements don't require a schema migration.

**Alternative considered.** Polymorphic event classes (`ToolCallEvent`, `SkillInvokeEvent`, etc.). Rejected — adds class explosion for marginal type safety; JSON serialization gets harder; pattern matching on `event_type` is sufficient and clearer.

**Trade-off accepted.** Some fields are `None` for any given event type. Consumers must check `event_type` before accessing union members. Mitigated by helper functions and (eventually) `TypeGuard`-typed accessors.

---

### D4: JSONL primary storage at `~/.claude/metrics.jsonl`, DuckDB query layer deferred

**Context.** Per-session metrics need to accumulate across sessions and across projects. Storage choice affects schema migration cost, query expressiveness, and dependency footprint.

**Decision.**
- **Primary persistence:** append-only JSONL at `~/.claude/metrics.jsonl`. This path is under the user's Claude config dir because it's cross-project local data, not tied to any one repo.
- **Query layer:** when Phase 1 demands ad-hoc analytics, run DuckDB directly over the JSONL — no migration required, DuckDB reads JSONL natively.

**Why.**
- Append-only JSONL is the simplest durable format: hard to corrupt, easy to back up, `jq`-queryable, idempotent to rebuild from source transcripts.
- DuckDB unlocks SQL when we need joins or windowed aggregates, without committing to a schema migration story.

**Alternatives considered.**
- *SQLite primary.* Rejected — schema migration for a personal tool is over-engineering. Every new field would require `ALTER TABLE` and a migration script; JSONL just adds optional fields.
- *Append to multiple files (one per agent or per month).* Rejected — adds file-organization logic for negligible scaling benefit at this volume.
- *Real-time event stream into a stream store.* See D7 — a real-time logger already exists for the per-event use case; coexist, not replace.

**Trade-off accepted.** Whole-file scans for queries; DuckDB mitigates but doesn't eliminate this at very large scale. At the author's volume (<10 sessions/day across all projects) the cost is invisible. If volume grows 100×, revisit and migrate to Parquet or SQLite then.

---

### D5: Two-channel skill extraction (Skill tool_use + `<command-name>` tag)

**Context.** Observation discovered that a prior in-house per-session metrics extractor (an internal artifact, 2026-04) captured only `Skill` tool calls from the agent-autonomous channel. User-typed slash commands like `/quality-gate` are expanded by the Claude Code harness into `<command-name>/quality-gate</command-name>...` inline in the user message — they do **not** produce a `Skill` tool call. Missing this channel undercounted invocations by ~60% across a 14-day sample.

**Decision.** The Claude Code adapter parses both channels and emits them as distinct events:

| Channel | Source | NormalizedEvent shape |
|---|---|---|
| **A (auto)** | `tool_use` with `name == "Skill"` | `event_type="skill_invoke", skill_channel="auto"` |
| **B (slash)** | `<command-name>/xxx</command-name>` in user message string | `event_type="skill_invoke", skill_channel="slash"` |

**Why.** The same skill invoked via two channels carries different diagnostic meaning:

- Channel A firing → the skill's description routing works; the agent picked it up from natural language.
- Channel B firing → description routing failed; the user had to invoke it manually.

Conflating them loses the most actionable signal in the entire system.

**Alternative considered.** Capture channel A only (the prior extractor's behavior). Rejected — empirically demonstrated to miss the dominant invocation mode for ~23 skills in the author's environment.

**Trade-off accepted.** Channel B detection requires string parsing of user message content, which is fragile if the `<command-name>` tag format changes. Mitigated by the `raw` escape hatch on `NormalizedEvent` — if format changes, only the adapter needs updating; downstream code is insulated.

---

### D6: Per-session metric grain (not per-event)

**Context.** Should `metrics.jsonl` store one record per event, or one record per session aggregating events?

**Decision.** One record per session. Each record contains aggregated counts, channel breakdown, and a list of distinct skill/agent invocations within the session.

**Why.** Session is the natural unit for "what did this work session accomplish." The most useful queries (skills used per session, channel distribution over time, session duration) are session-level. Per-event grain inflates storage and makes session-bounded reasoning harder.

**Alternative considered.** Per-event record. Rejected — the per-event use case is already covered by the real-time `skill-usage.log` logger (see D7). Duplicating it is wasteful.

**Trade-off accepted.** Loses per-event timing within a session. If that becomes important, we re-derive from source transcripts on demand. Storage remains source-of-truth at the JSONL session level.

---

### D7: Coexist with the existing real-time skill logger, do not replace

**Context.** In Claude Code, a `PreToolUse` hook on `Skill` already writes one line per skill call to `~/.claude/skill-usage.log` — real-time, channel-A only. This is a working data source that solves the per-event use case at near-zero cost.

**Decision.** Leave `skill-usage.log` running. `agent-trace` consumes transcripts independently and produces session-grain output. Two different surfaces, two different consumers.

**Why.**
- `skill-usage.log` is real-time and channel-A only; `agent-trace` is per-session and dual-channel.
- Replacing `skill-usage.log` would force `agent-trace` to be running and reliable before it's mature.
- Different abstractions answer different questions; premature consolidation locks in the wrong shape.

**Alternative considered.** Have `agent-trace` tail and consume `skill-usage.log` as one of its inputs. Rejected — couples Phase 1 to a real-time path it doesn't yet need.

**Trade-off accepted.** Two systems with overlapping observations until one is clearly redundant. Re-evaluate after Phase 2 has been stable for two weeks.

---

### D8: Repo name `agent-trace`

**Decision.** `agent-trace`.

**Why.** "Trace" carries the right telemetry connotation (distributed tracing, log trace). "Agent" scopes it to AI agents specifically. Two short hyphenated words, easy to type, namespace available on PyPI at planning time.

**Alternatives considered.** `agent-tele` (telemetry abbreviation — meaning unclear), `aitrace` (too generic; high namespace collision risk), `skilltrace` (too narrow — tools and subagents are also observed), `coding-agent-obs` (too long; "obs" overloaded with Obsidian).

**Trade-off accepted.** None significant.

---

## Migration Notes

### M1: Retire the in-house per-session extractor

A prior per-session metrics extractor (internal artifact, 2026-04) has a `skills_invoked` field with the channel-A blind spot fixed by D5. The Claude Code adapter absorbs and corrects that logic. The original file is **kept temporarily** as a reference cross-check during Phase 1 — run both, diff outputs. After Phase 2 hook wiring has been stable for two weeks, the original is deleted.

### M2: Backfill before wiring SessionEnd hook

The author has 14+ days of existing transcripts stored locally per agent. Phase 1 starts with a one-shot backfill:

```bash
for f in <claude-config-dir>/projects/*/*.jsonl; do
    agent-trace ingest --adapter claude-code "$f"
done >> ~/.claude/metrics.jsonl
```

This produces immediate historical metrics before any hook is wired. The subsequent SessionEnd hook (Phase 2) appends new sessions only. Backfill is idempotent — the aggregator deduplicates by `session_id`.

---

## Open Questions

### Q1: When is the `NormalizedEvent` ABI stable enough to commit to?

**Question.** What triggers the bump from `0.x` to `1.0`?

**Proposed answer.** ABI remains unstable until a second adapter (Gemini or Codex) is implemented end-to-end and pressure-tests it. The stability commitment happens only after that.

**Why this matters.** Downstream consumers (custom dashboards, eval scripts) need to know whether to pin a version. Committing too early freezes the wrong shape.

### Q2: What triggers Phase 3?

**Question.** When does building the second adapter (Gemini or Codex) become real work, not speculation?

**Proposed answer.** When the author has 5+ real sessions on that agent in any rolling 7-day window. Speculative implementation before that violates D2's YAGNI stance.

**Why this matters.** Without an explicit criterion, "future multi-agent" becomes a moving target that pulls effort away from Phase 1/2 maturity.

---

## Phase Plan

| Phase | Scope | Status |
|---|---|---|
| **0** | Schema design, repo skeleton, planning docs | **This commit** |
| **1** | Claude Code adapter + backfill CLI + aggregator with dual-channel detection | Next |
| **2** | SessionEnd hook auto-ingest; retire orphan extractor (per M1) | After Phase 1 stable for 2 weeks |
| **3** | Second adapter (Gemini or Codex), gated by Q2 criterion | Conditional |

### Phase 1 deliverables

- `agent_trace/core/events.py` — `NormalizedEvent` dataclass
- `agent_trace/core/storage.py` — append/read `metrics.jsonl`
- `agent_trace/core/aggregate.py` — usage table, dead-skill diff, channel breakdown
- `agent_trace/adapters/base.py` — abstract `Adapter`
- `agent_trace/adapters/claude_code.py` — JSONL parser with dual-channel detection
- `agent_trace/cli.py` — `agent-trace ingest | report | backfill`
- `tests/fixtures/claude-code/*.jsonl` — minimal anonymized samples
- `tests/test_claude_code_adapter.py`
