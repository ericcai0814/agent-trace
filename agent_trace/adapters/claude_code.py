"""Claude Code transcript adapter.

Implements dual-channel skill detection per docs/PLANNING.md D5:
- Channel A (auto): assistant tool_use with name=Skill
- Channel B (slash): <command-name>/.../<command-name> in user message string

Adapter emits raw signals; filtering against the skill whitelist
(built-ins, plugin-namespace noise) is done by the aggregator at
query time, not here — that keeps backfill output stable as the
whitelist evolves.
"""

from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from agent_trace.adapters.base import Adapter
from agent_trace.core.events import NormalizedEvent

COMMAND_NAME_RE = re.compile(
    r"<command-name>/([a-z0-9_:-]+)</command-name>", re.IGNORECASE
)


def _normalize_skill_name(name: str) -> str:
    """Collapse `ns:leaf` to `leaf` when ns == leaf (e.g. mgrep:mgrep → mgrep)."""
    if ":" in name:
        parts = name.split(":")
        if len(parts) == 2 and parts[0] == parts[1]:
            return parts[1]
    return name


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _project_from_cwd(cwd: str | None) -> str | None:
    if not cwd:
        return None
    return Path(cwd).name


DEFAULT_SKILL_ROOTS = (
    Path.home() / ".claude" / "skills",
    Path.home() / ".agents" / "skills",
)
DEFAULT_PLUGIN_SKILL_GLOB = str(
    Path.home() / ".claude" / "plugins" / "marketplaces" / "*" / "plugins" / "*" / "skills"
)


def _parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    body = text[3:end]
    out: dict[str, str] = {}
    for line in body.splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip("'\"")
    return out


def load_skill_whitelist(
    extra_roots: Iterator[Path] | None = None,
) -> dict[str, dict[str, Any]]:
    """Discover installed Claude Code skills via SKILL.md frontmatter.

    Returns dict[skill_name → {disable_model_invocation: bool, source_path: str}].
    """
    roots: list[Path] = list(DEFAULT_SKILL_ROOTS)
    if extra_roots:
        roots.extend(extra_roots)

    seen_dirs: set[Path] = set()
    for r in roots:
        if r.is_dir():
            for child in r.iterdir():
                resolved = child.resolve()
                if resolved.is_dir():
                    seen_dirs.add(resolved)

    for plugin_skills_dir in glob.glob(DEFAULT_PLUGIN_SKILL_GLOB):
        p = Path(plugin_skills_dir)
        if not p.is_dir():
            continue
        for child in p.iterdir():
            resolved = child.resolve()
            if resolved.is_dir():
                seen_dirs.add(resolved)

    out: dict[str, dict[str, Any]] = {}
    for d in seen_dirs:
        md = d / "SKILL.md"
        if not md.is_file():
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        name = fm.get("name") or d.name
        disable = fm.get("disable-model-invocation", "").lower() == "true"
        out[name] = {
            "disable_model_invocation": disable,
            "source_path": str(md),
        }
    return out


class ClaudeCodeAdapter(Adapter):
    name = "claude-code"

    def parse(self, transcript_path: Path) -> Iterator[NormalizedEvent]:
        with open(transcript_path, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield from self._events_from(evt)

    def _events_from(self, evt: dict[str, Any]) -> Iterator[NormalizedEvent]:
        t = evt.get("type")
        if t == "user":
            yield from self._from_user(evt)
        elif t == "assistant":
            yield from self._from_assistant(evt)

    def _from_user(self, evt: dict[str, Any]) -> Iterator[NormalizedEvent]:
        content = evt.get("message", {}).get("content")
        if not isinstance(content, str):
            return
        ts = _parse_ts(evt["timestamp"])
        session_id = evt.get("sessionId", "")
        project = _project_from_cwd(evt.get("cwd"))

        matches = list(COMMAND_NAME_RE.finditer(content))
        if matches:
            for m in matches:
                yield NormalizedEvent(
                    ts=ts,
                    agent="claude-code",
                    session_id=session_id,
                    event_type="skill_invoke",
                    project=project,
                    skill_name=m.group(1),
                    skill_channel="slash",
                    raw={"channel": "slash", "uuid": evt.get("uuid")},
                )
            return

        yield NormalizedEvent(
            ts=ts,
            agent="claude-code",
            session_id=session_id,
            event_type="user_prompt",
            project=project,
            user_text=content[:500],
            raw={"uuid": evt.get("uuid")},
        )

    def _from_assistant(self, evt: dict[str, Any]) -> Iterator[NormalizedEvent]:
        ts = _parse_ts(evt["timestamp"])
        session_id = evt.get("sessionId", "")
        project = _project_from_cwd(evt.get("cwd"))
        blocks = evt.get("message", {}).get("content")
        if not isinstance(blocks, list):
            return
        has_content = any(
            isinstance(b, dict)
            and (
                b.get("type") == "tool_use"
                or (b.get("type") == "text" and b.get("text", "").strip())
            )
            for b in blocks
        )
        if has_content:
            yield NormalizedEvent(
                ts=ts,
                agent="claude-code",
                session_id=session_id,
                event_type="assistant_message",
                project=project,
                raw={"uuid": evt.get("uuid")},
            )
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_name = block.get("name")
            input_blob = block.get("input") or {}
            if tool_name == "Skill":
                raw_skill = input_blob.get("skill", "")
                yield NormalizedEvent(
                    ts=ts,
                    agent="claude-code",
                    session_id=session_id,
                    event_type="skill_invoke",
                    project=project,
                    tool_name="Skill",
                    skill_name=_normalize_skill_name(raw_skill),
                    skill_channel="auto",
                    raw={"channel": "auto", "raw_skill": raw_skill, "uuid": evt.get("uuid")},
                )
            elif tool_name == "Agent":
                yield NormalizedEvent(
                    ts=ts,
                    agent="claude-code",
                    session_id=session_id,
                    event_type="subagent_spawn",
                    project=project,
                    tool_name="Agent",
                    subagent_name=input_blob.get("subagent_type", "general-purpose"),
                    raw={"uuid": evt.get("uuid")},
                )
            else:
                yield NormalizedEvent(
                    ts=ts,
                    agent="claude-code",
                    session_id=session_id,
                    event_type="tool_call",
                    project=project,
                    tool_name=tool_name,
                    raw={"uuid": evt.get("uuid")},
                )
