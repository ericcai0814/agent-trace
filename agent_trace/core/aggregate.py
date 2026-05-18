"""Per-session aggregation and cross-session reports.

`session_record` turns a NormalizedEvent stream into one session dict
suitable for appending to metrics.jsonl. Cross-session reports
(`usage_table`, `dead_skills`, `channel_breakdown`) consume those
records and surface the dual-channel signal D5 is built to expose.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Iterable

from agent_trace.core.events import NormalizedEvent


def session_record(
    events: Iterable[NormalizedEvent],
    agent: str,
    *,
    session_id_fallback: str | None = None,
) -> dict[str, Any]:
    events = list(events)
    if not events:
        return {
            "session_id": session_id_fallback or "",
            "agent": agent,
            "event_count": 0,
        }

    session_id = events[0].session_id or session_id_fallback or ""
    project = events[0].project

    timestamps = sorted(e.ts for e in events)
    started_at = timestamps[0]
    ended_at = timestamps[-1]
    duration_min = max(0, int((ended_at - started_at).total_seconds() // 60))

    user_messages = sum(1 for e in events if e.event_type == "user_prompt")
    user_messages += sum(
        1 for e in events
        if e.event_type == "skill_invoke" and e.skill_channel == "slash"
    )
    assistant_messages = sum(
        1 for e in events if e.event_type == "assistant_message"
    )

    tool_counts: Counter[str] = Counter()
    skill_counter: Counter[tuple[str, str]] = Counter()
    subagent_counter: Counter[str] = Counter()
    for e in events:
        if e.tool_name:
            tool_counts[e.tool_name] += 1
        if e.event_type == "skill_invoke" and e.skill_name and e.skill_channel:
            skill_counter[(e.skill_name, e.skill_channel)] += 1
        if e.event_type == "subagent_spawn" and e.subagent_name:
            subagent_counter[e.subagent_name] += 1

    return {
        "session_id": session_id,
        "agent": agent,
        "project": project,
        "started_at": _iso(started_at),
        "ended_at": _iso(ended_at),
        "duration_minutes": duration_min,
        "user_messages": user_messages,
        "assistant_messages": assistant_messages,
        "tool_calls": dict(tool_counts),
        "skills_invoked": [
            {"name": name, "channel": channel, "count": count}
            for (name, channel), count in sorted(
                skill_counter.items(), key=lambda x: (-x[1], x[0])
            )
        ],
        "subagents_spawned": [
            {"name": name, "count": count}
            for name, count in sorted(
                subagent_counter.items(), key=lambda x: (-x[1], x[0])
            )
        ],
    }


def usage_table(
    records: Iterable[dict[str, Any]],
    *,
    whitelist: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Per-skill totals + channel split, across all sessions.

    Built-ins like /clear are filtered out when a whitelist is supplied.
    """
    totals: dict[str, Counter[str]] = defaultdict(Counter)
    for rec in records:
        for s in rec.get("skills_invoked", []):
            name = s["name"]
            if whitelist is not None and name not in whitelist:
                continue
            totals[name][s["channel"]] += s["count"]

    rows = []
    for name, by_chan in totals.items():
        total = sum(by_chan.values())
        rows.append(
            {
                "skill": name,
                "total": total,
                "auto": by_chan.get("auto", 0),
                "slash": by_chan.get("slash", 0),
                "hook": by_chan.get("hook", 0),
            }
        )
    rows.sort(key=lambda r: (-r["total"], r["skill"]))
    return rows


def channel_breakdown(records: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Total invocations per channel across all records."""
    totals: Counter[str] = Counter()
    for rec in records:
        for s in rec.get("skills_invoked", []):
            totals[s["channel"]] += s["count"]
    return dict(totals)


def dead_skills(
    records: Iterable[dict[str, Any]],
    *,
    whitelist: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Skills present in whitelist but never observed.

    Whitelist values may carry `disable_model_invocation: bool` — surfaced
    on the report so a slash-only skill isn't misread as "broken
    description routing".
    """
    invoked: set[str] = set()
    for rec in records:
        for s in rec.get("skills_invoked", []):
            invoked.add(s["name"])

    rows = []
    for name, meta in whitelist.items():
        if name in invoked:
            continue
        rows.append(
            {
                "skill": name,
                "slash_only": bool(meta.get("disable_model_invocation")),
            }
        )
    rows.sort(key=lambda r: (r["slash_only"], r["skill"]))
    return rows


def _iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")
