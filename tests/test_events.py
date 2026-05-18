from datetime import datetime, timezone

from agent_trace.core.events import NormalizedEvent


def _sample_skill_event() -> NormalizedEvent:
    return NormalizedEvent(
        ts=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc),
        agent="claude-code",
        session_id="abc",
        event_type="skill_invoke",
        project="proj",
        skill_name="mgrep",
        skill_channel="auto",
        raw={"name": "Skill"},
    )


def test_round_trip_skill_invoke():
    ev = _sample_skill_event()
    restored = NormalizedEvent.from_dict(ev.to_dict())
    assert restored == ev


def test_round_trip_subagent_spawn():
    ev = NormalizedEvent(
        ts=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc),
        agent="claude-code",
        session_id="abc",
        event_type="subagent_spawn",
        subagent_name="Explore",
    )
    assert NormalizedEvent.from_dict(ev.to_dict()) == ev


def test_round_trip_user_prompt_with_unicode():
    ev = NormalizedEvent(
        ts=datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc),
        agent="claude-code",
        session_id="abc",
        event_type="user_prompt",
        user_text="請幫我跑 git-workflow",
    )
    assert NormalizedEvent.from_dict(ev.to_dict()) == ev


def test_ts_serialized_as_iso_z():
    ev = _sample_skill_event()
    assert ev.to_dict()["ts"].endswith("Z")


def test_raw_defaults_to_empty_dict():
    ev = NormalizedEvent(
        ts=datetime(2026, 5, 15, tzinfo=timezone.utc),
        agent="claude-code",
        session_id="abc",
        event_type="tool_call",
        tool_name="Bash",
    )
    assert ev.raw == {}
    assert NormalizedEvent.from_dict(ev.to_dict()).raw == {}
