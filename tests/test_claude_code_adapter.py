from collections import Counter
from pathlib import Path

from agent_trace.adapters.claude_code import (
    ClaudeCodeAdapter,
    _normalize_skill_name,
)
from agent_trace.core.events import NormalizedEvent

FIXTURES = Path(__file__).parent / "fixtures" / "claude-code"


def _parse(name: str) -> list[NormalizedEvent]:
    return list(ClaudeCodeAdapter().parse(FIXTURES / name))


def test_namespace_collapse():
    assert _normalize_skill_name("mgrep:mgrep") == "mgrep"
    assert _normalize_skill_name("mgrep") == "mgrep"
    assert _normalize_skill_name("plugin:subskill") == "plugin:subskill"


def test_rich_session_event_counts():
    events = _parse("session_rich.jsonl")
    by_type = Counter(e.event_type for e in events)
    assert by_type["skill_invoke"] == 5  # 2 auto + 3 slash
    assert by_type["subagent_spawn"] == 1
    assert by_type["tool_call"] == 1  # Bash
    assert by_type["user_prompt"] == 0
    assert by_type["assistant_message"] == 5  # five assistant turns in fixture


def test_rich_session_channel_split():
    events = _parse("session_rich.jsonl")
    skills = [e for e in events if e.event_type == "skill_invoke"]
    by_channel = Counter(e.skill_channel for e in skills)
    assert by_channel["auto"] == 2
    assert by_channel["slash"] == 3


def test_rich_session_namespace_normalized_in_emission():
    events = _parse("session_rich.jsonl")
    auto_names = [
        e.skill_name for e in events if e.skill_channel == "auto"
    ]
    assert auto_names == ["mgrep", "mgrep"]


def test_rich_session_slash_names_include_builtins_unfiltered():
    events = _parse("session_rich.jsonl")
    slash_names = {
        e.skill_name for e in events if e.skill_channel == "slash"
    }
    assert slash_names == {"git-workflow", "clear", "grill-with-docs"}


def test_rich_session_subagent_name_captured():
    events = _parse("session_rich.jsonl")
    sub = next(e for e in events if e.event_type == "subagent_spawn")
    assert sub.subagent_name == "Explore"
    assert sub.tool_name == "Agent"


def test_rich_session_raw_skill_preserved_on_namespace_collapse():
    events = _parse("session_rich.jsonl")
    collapsed = [
        e for e in events
        if e.skill_channel == "auto" and e.raw.get("raw_skill") == "mgrep:mgrep"
    ]
    assert len(collapsed) == 1
    assert collapsed[0].skill_name == "mgrep"


def test_empty_session_yields_only_message_markers():
    events = _parse("session_empty.jsonl")
    types = [e.event_type for e in events]
    assert types == ["user_prompt", "assistant_message"]
    assert events[0].user_text == "hello world"


def test_session_id_and_project_propagated():
    events = _parse("session_rich.jsonl")
    assert all(e.session_id == "rich-session" for e in events)
    assert all(e.project == "proj" for e in events)


def test_all_events_serialize_round_trip():
    events = _parse("session_rich.jsonl")
    for e in events:
        assert NormalizedEvent.from_dict(e.to_dict()) == e
