import json
from pathlib import Path

from agent_trace.core.storage import append, dedupe_by_session_id, read_all


def test_append_and_read_round_trip(tmp_path: Path):
    p = tmp_path / "metrics.jsonl"
    append({"session_id": "a", "n": 1}, p)
    append({"session_id": "b", "n": 2}, p)
    out = list(read_all(p))
    assert out == [{"session_id": "a", "n": 1}, {"session_id": "b", "n": 2}]


def test_read_all_handles_missing_file(tmp_path: Path):
    p = tmp_path / "nope.jsonl"
    assert list(read_all(p)) == []


def test_read_all_skips_blank_and_bad_lines(tmp_path: Path):
    p = tmp_path / "metrics.jsonl"
    p.write_text(
        json.dumps({"session_id": "a"}) + "\n"
        + "\n"
        + "not json\n"
        + json.dumps({"session_id": "b"}) + "\n"
    )
    out = list(read_all(p))
    assert [r["session_id"] for r in out] == ["a", "b"]


def test_dedupe_keeps_last_write_per_session():
    records = [
        {"session_id": "a", "n": 1},
        {"session_id": "b", "n": 1},
        {"session_id": "a", "n": 2},
    ]
    out = dedupe_by_session_id(records)
    assert sorted(out, key=lambda r: r["session_id"]) == [
        {"session_id": "a", "n": 2},
        {"session_id": "b", "n": 1},
    ]


def test_append_preserves_unicode(tmp_path: Path):
    p = tmp_path / "m.jsonl"
    append({"session_id": "a", "user_text": "請幫我跑"}, p)
    out = list(read_all(p))
    assert out[0]["user_text"] == "請幫我跑"
