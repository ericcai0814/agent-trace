"""SessionEnd hook entry for Claude Code transcripts.

Reads the SessionEnd JSON payload from stdin, runs the Claude Code adapter
on the transcript, and appends one normalized session record to the
metrics file.

Never blocks SessionEnd — all errors are written to an error log and
the process always exits 0.

Wire into ``~/.claude/settings.json`` via ``agent-trace install-hook``.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def _error_log_path() -> Path:
    override = os.environ.get("AGENT_TRACE_ERROR_LOG")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "agent-trace.error.log"


def _log_error(msg: str) -> None:
    try:
        log = _error_log_path()
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fp:
            fp.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except OSError:
        pass


def main() -> int:
    try:
        raw = sys.stdin.read()
    except OSError as e:
        _log_error(f"stdin read failed: {e}")
        return 0
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        _log_error(f"stdin JSON decode failed: {e}")
        return 0

    transcript = payload.get("transcript_path") if isinstance(payload, dict) else None
    if not transcript:
        return 0
    transcript_path = Path(transcript)
    if not transcript_path.is_file():
        return 0

    try:
        from agent_trace.adapters.claude_code import ClaudeCodeAdapter
        from agent_trace.core.aggregate import session_record
        from agent_trace.core.storage import append

        adapter = ClaudeCodeAdapter()
        events = list(adapter.parse(transcript_path))
        if not events:
            return 0
        rec = session_record(events, agent=adapter.name)
        if rec.get("session_id"):
            append(rec)
    except Exception:
        _log_error(f"hook error: {traceback.format_exc()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
