"""NormalizedEvent — the agent-agnostic ABI.

See docs/PLANNING.md D3 for design rationale. Schema is unstable
until a second adapter implementation pressure-tests it (Q1).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

EventType = Literal[
    "tool_call",
    "skill_invoke",
    "subagent_spawn",
    "user_prompt",
    "assistant_message",
]
Agent = Literal["claude-code", "gemini-cli", "codex"]
SkillChannel = Literal["auto", "slash", "hook"]


@dataclass
class NormalizedEvent:
    ts: datetime
    agent: Agent
    session_id: str
    event_type: EventType
    project: str | None = None
    tool_name: str | None = None
    skill_name: str | None = None
    skill_channel: SkillChannel | None = None
    subagent_name: str | None = None
    user_text: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NormalizedEvent":
        ts_raw = d["ts"]
        if isinstance(ts_raw, str):
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        else:
            ts = ts_raw
        return cls(
            ts=ts,
            agent=d["agent"],
            session_id=d["session_id"],
            event_type=d["event_type"],
            project=d.get("project"),
            tool_name=d.get("tool_name"),
            skill_name=d.get("skill_name"),
            skill_channel=d.get("skill_channel"),
            subagent_name=d.get("subagent_name"),
            user_text=d.get("user_text"),
            raw=d.get("raw") or {},
        )
