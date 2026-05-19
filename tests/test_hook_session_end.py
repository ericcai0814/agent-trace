import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from agent_trace.hooks import session_end

FIXTURES = Path(__file__).parent / "fixtures" / "claude-code"


def _run(monkeypatch, payload: str, tmp_path: Path) -> int:
    metrics = tmp_path / "metrics.jsonl"
    error_log = tmp_path / "error.log"
    monkeypatch.setenv("AGENT_TRACE_METRICS_PATH", str(metrics))
    monkeypatch.setenv("AGENT_TRACE_ERROR_LOG", str(error_log))
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = session_end.main()
    return rc


def test_empty_stdin_is_noop(monkeypatch, tmp_path):
    rc = _run(monkeypatch, "", tmp_path)
    assert rc == 0
    assert not (tmp_path / "metrics.jsonl").exists()


def test_malformed_json_logs_and_returns_zero(monkeypatch, tmp_path):
    rc = _run(monkeypatch, "{not-json", tmp_path)
    assert rc == 0
    assert not (tmp_path / "metrics.jsonl").exists()
    assert (tmp_path / "error.log").is_file()


def test_missing_transcript_path_is_noop(monkeypatch, tmp_path):
    rc = _run(monkeypatch, json.dumps({"session_id": "x"}), tmp_path)
    assert rc == 0
    assert not (tmp_path / "metrics.jsonl").exists()


def test_nonexistent_transcript_is_noop(monkeypatch, tmp_path):
    payload = json.dumps({"transcript_path": "/tmp/does-not-exist.jsonl"})
    rc = _run(monkeypatch, payload, tmp_path)
    assert rc == 0
    assert not (tmp_path / "metrics.jsonl").exists()


def test_valid_transcript_writes_one_record(monkeypatch, tmp_path):
    transcript = FIXTURES / "session_rich.jsonl"
    payload = json.dumps({"transcript_path": str(transcript)})
    rc = _run(monkeypatch, payload, tmp_path)
    assert rc == 0
    metrics = tmp_path / "metrics.jsonl"
    assert metrics.is_file()
    lines = metrics.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["session_id"] == "rich-session"
    assert rec["agent"] == "claude-code"


def test_empty_transcript_does_not_write(monkeypatch, tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    payload = json.dumps({"transcript_path": str(empty)})
    rc = _run(monkeypatch, payload, tmp_path)
    assert rc == 0
    assert not (tmp_path / "metrics.jsonl").exists()


def test_non_dict_payload_is_noop(monkeypatch, tmp_path):
    rc = _run(monkeypatch, json.dumps(["a", "list"]), tmp_path)
    assert rc == 0
    assert not (tmp_path / "metrics.jsonl").exists()
