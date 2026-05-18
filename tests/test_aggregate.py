from pathlib import Path

from agent_trace.adapters.claude_code import ClaudeCodeAdapter
from agent_trace.core.aggregate import (
    channel_breakdown,
    dead_skills,
    session_record,
    usage_table,
)

FIXTURES = Path(__file__).parent / "fixtures" / "claude-code"


def _record(name: str) -> dict:
    events = list(ClaudeCodeAdapter().parse(FIXTURES / name))
    return session_record(events, agent="claude-code")


def test_session_record_rich():
    rec = _record("session_rich.jsonl")
    assert rec["session_id"] == "rich-session"
    assert rec["agent"] == "claude-code"
    assert rec["project"] == "proj"
    assert rec["started_at"].startswith("2026-05-15T09:00:00")
    assert rec["duration_minutes"] == 0  # all events within same minute
    assert rec["user_messages"] == 3  # 2 string prompts + slash-only "/clear" line
    assert rec["assistant_messages"] == 5


def test_session_record_tool_call_counts():
    rec = _record("session_rich.jsonl")
    # tool_calls reflects real tool_use blocks only — slash invocations do
    # NOT travel through the tool channel, so they do not count here.
    assert rec["tool_calls"]["Skill"] == 2  # only the 2 channel-A Skill uses
    assert rec["tool_calls"]["Agent"] == 1
    assert rec["tool_calls"]["Bash"] == 1


def test_session_record_skills_invoked_grouped_by_channel():
    rec = _record("session_rich.jsonl")
    skills = rec["skills_invoked"]
    by_key = {(s["name"], s["channel"]): s["count"] for s in skills}
    assert by_key[("mgrep", "auto")] == 2  # mgrep + mgrep:mgrep collapsed
    assert by_key[("git-workflow", "slash")] == 1
    assert by_key[("clear", "slash")] == 1
    assert by_key[("grill-with-docs", "slash")] == 1


def test_session_record_subagents():
    rec = _record("session_rich.jsonl")
    assert rec["subagents_spawned"] == [{"name": "Explore", "count": 1}]


def test_session_record_empty_session():
    rec = _record("session_empty.jsonl")
    assert rec["skills_invoked"] == []
    assert rec["subagents_spawned"] == []
    assert rec["tool_calls"] == {}
    assert rec["assistant_messages"] == 1
    assert rec["user_messages"] == 1


def test_usage_table_filters_with_whitelist():
    rec = _record("session_rich.jsonl")
    table = usage_table([rec], whitelist={"mgrep", "git-workflow", "grill-with-docs"})
    skills = {r["skill"] for r in table}
    assert "clear" not in skills  # built-in filtered out
    assert "mgrep" in skills
    mgrep_row = next(r for r in table if r["skill"] == "mgrep")
    assert mgrep_row["auto"] == 2
    assert mgrep_row["slash"] == 0
    assert mgrep_row["total"] == 2


def test_usage_table_without_whitelist_includes_everything():
    rec = _record("session_rich.jsonl")
    table = usage_table([rec])
    assert any(r["skill"] == "clear" for r in table)


def test_channel_breakdown_unfiltered():
    rec = _record("session_rich.jsonl")
    cb = channel_breakdown([rec])
    assert cb == {"auto": 2, "slash": 3}


def test_dead_skills_diff_against_whitelist():
    rec = _record("session_rich.jsonl")
    whitelist = {
        "mgrep": {"disable_model_invocation": False},
        "git-workflow": {"disable_model_invocation": False},
        "grill-with-docs": {"disable_model_invocation": False},
        "tdd": {"disable_model_invocation": True},  # never invoked, slash-only
        "quality-gate": {"disable_model_invocation": False},  # never invoked
    }
    dead = dead_skills([rec], whitelist=whitelist)
    names = {d["skill"] for d in dead}
    assert names == {"tdd", "quality-gate"}
    tdd = next(d for d in dead if d["skill"] == "tdd")
    assert tdd["slash_only"] is True
    qg = next(d for d in dead if d["skill"] == "quality-gate")
    assert qg["slash_only"] is False
