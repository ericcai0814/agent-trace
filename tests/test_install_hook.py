import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from agent_trace.cli import HOOK_COMMAND, main


def _run_install(monkeypatch, tmp_path: Path) -> tuple[int, str, Path]:
    settings = tmp_path / "settings.json"
    monkeypatch.setenv("AGENT_TRACE_SETTINGS_PATH", str(settings))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["install-hook", "--adapter", "claude-code"])
    return rc, buf.getvalue(), settings


def test_install_into_fresh_settings(monkeypatch, tmp_path):
    rc, out, settings = _run_install(monkeypatch, tmp_path)
    assert rc == 0
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["hooks"]["SessionEnd"] == [
        {"matcher": "*", "hooks": [{"type": "command", "command": HOOK_COMMAND}]}
    ]
    assert "installed" in out


def test_install_appends_to_existing(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    existing = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo x"}]}
            ],
            "SessionEnd": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "echo old"}]}
            ],
        }
    }
    settings.write_text(json.dumps(existing), encoding="utf-8")
    monkeypatch.setenv("AGENT_TRACE_SETTINGS_PATH", str(settings))

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["install-hook", "--adapter", "claude-code"])
    assert rc == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    session_end = data["hooks"]["SessionEnd"]
    assert len(session_end) == 2
    commands = [h["command"] for entry in session_end for h in entry["hooks"]]
    assert "echo old" in commands
    assert HOOK_COMMAND in commands
    assert data["hooks"]["PreToolUse"] == existing["hooks"]["PreToolUse"]


def test_install_creates_backup_when_settings_exists(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    monkeypatch.setenv("AGENT_TRACE_SETTINGS_PATH", str(settings))

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["install-hook", "--adapter", "claude-code"])
    assert rc == 0

    backups = list(tmp_path.glob("settings.json.bak-*"))
    assert len(backups) == 1
    original = json.loads(backups[0].read_text(encoding="utf-8"))
    assert original == {"foo": "bar"}


def test_install_is_idempotent(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    monkeypatch.setenv("AGENT_TRACE_SETTINGS_PATH", str(settings))

    for _ in range(2):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["install-hook", "--adapter", "claude-code"])
        assert rc == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    matches = [
        h
        for entry in data["hooks"]["SessionEnd"]
        for h in entry["hooks"]
        if HOOK_COMMAND in h["command"]
    ]
    assert len(matches) == 1


def test_install_refuses_non_object_hooks(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": "not-an-object"}), encoding="utf-8")
    monkeypatch.setenv("AGENT_TRACE_SETTINGS_PATH", str(settings))

    with pytest.raises(SystemExit) as exc_info:
        main(["install-hook", "--adapter", "claude-code"])
    assert "'hooks' is not an object" in str(exc_info.value)


def test_install_refuses_malformed_settings(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("AGENT_TRACE_SETTINGS_PATH", str(settings))

    with pytest.raises(SystemExit) as exc_info:
        main(["install-hook", "--adapter", "claude-code"])
    assert "malformed" in str(exc_info.value).lower()
    # ensure file is not touched
    assert settings.read_text(encoding="utf-8") == "{not json"
