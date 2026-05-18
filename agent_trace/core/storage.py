"""metrics.jsonl read/write.

Per docs/PLANNING.md D4: append-only JSONL is the primary storage.
DuckDB is layered on top later when ad-hoc analytics need SQL.

Backfill is idempotent — `dedupe_by_session_id` keeps last-write-wins.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Iterator

DEFAULT_METRICS_PATH = Path(
    os.environ.get("AGENT_TRACE_METRICS_PATH")
    or Path.home() / ".claude" / "metrics.jsonl"
)


def append(record: dict[str, Any], path: Path = DEFAULT_METRICS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_all(path: Path = DEFAULT_METRICS_PATH) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def dedupe_by_session_id(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for r in records:
        sid = r.get("session_id")
        if sid:
            by_id[sid] = r
    return list(by_id.values())
