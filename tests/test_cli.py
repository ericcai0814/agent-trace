import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from agent_trace.cli import main

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "claude-code" / "session_rich.jsonl"
)


def test_ingest_emits_one_session_record_to_stdout(tmp_path: Path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["ingest", "--adapter", "claude-code", str(FIXTURE_PATH)])
    assert rc == 0
    line = buf.getvalue().strip()
    record = json.loads(line)
    assert record["session_id"] == "rich-session"
    assert record["agent"] == "claude-code"
    assert any(s["channel"] == "slash" for s in record["skills_invoked"])


def test_ingest_appends_well_to_metrics_file(tmp_path: Path):
    metrics = tmp_path / "metrics.jsonl"
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["ingest", "--adapter", "claude-code", str(FIXTURE_PATH)])
    metrics.write_text(buf.getvalue())
    records = [json.loads(l) for l in metrics.read_text().splitlines() if l.strip()]
    assert len(records) == 1
    assert records[0]["agent"] == "claude-code"


def test_report_channels_runs_on_real_metrics(tmp_path: Path, monkeypatch):
    metrics = tmp_path / "metrics.jsonl"
    rec = {
        "session_id": "x",
        "agent": "claude-code",
        "skills_invoked": [
            {"name": "mgrep", "channel": "auto", "count": 3},
            {"name": "git-workflow", "channel": "slash", "count": 2},
        ],
    }
    metrics.write_text(json.dumps(rec) + "\n")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["report", "channels", "--metrics", str(metrics)])
    assert rc == 0
    out = buf.getvalue()
    assert "auto" in out and "slash" in out
    assert "3" in out and "2" in out
