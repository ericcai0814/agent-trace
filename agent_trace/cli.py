"""agent-trace command-line interface.

Subcommands:
  ingest    parse one transcript, emit one session record to stdout
  backfill  scan all known transcripts, append records to metrics.jsonl
  report    aggregate metrics.jsonl into usage / dead-skill / channel views
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Iterable

from agent_trace.adapters.base import Adapter
from agent_trace.adapters.claude_code import ClaudeCodeAdapter, load_skill_whitelist
from agent_trace.core.aggregate import (
    channel_breakdown,
    dead_skills,
    session_record,
    usage_table,
)
from agent_trace.core.storage import (
    DEFAULT_METRICS_PATH,
    append,
    dedupe_by_session_id,
    read_all,
)

ADAPTERS: dict[str, type[Adapter]] = {
    "claude-code": ClaudeCodeAdapter,
}

CLAUDE_CODE_TRANSCRIPT_GLOB = str(
    Path.home() / ".claude" / "projects" / "*" / "*.jsonl"
)


def _get_adapter(name: str) -> Adapter:
    cls = ADAPTERS.get(name)
    if cls is None:
        raise SystemExit(f"unknown adapter: {name}. known: {sorted(ADAPTERS)}")
    return cls()


def cmd_ingest(args: argparse.Namespace) -> int:
    adapter = _get_adapter(args.adapter)
    events = adapter.parse(Path(args.transcript))
    record = session_record(events, agent=adapter.name)
    json.dump(record, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    adapter = _get_adapter(args.adapter)
    out_path = Path(args.out) if args.out else DEFAULT_METRICS_PATH

    if args.adapter == "claude-code":
        sources: Iterable[str] = sorted(glob.glob(CLAUDE_CODE_TRANSCRIPT_GLOB))
    else:
        sources = []

    written = 0
    for src in sources:
        events = list(adapter.parse(Path(src)))
        if not events:
            continue
        rec = session_record(events, agent=adapter.name)
        if not rec.get("session_id"):
            continue
        append(rec, out_path)
        written += 1

    print(f"backfill: wrote {written} session records to {out_path}", file=sys.stderr)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    metrics_path = Path(args.metrics) if args.metrics else DEFAULT_METRICS_PATH
    records = dedupe_by_session_id(read_all(metrics_path))

    if args.kind == "usage":
        whitelist = None
        if not args.no_filter:
            whitelist = set(load_skill_whitelist().keys())
        rows = usage_table(records, whitelist=whitelist)
        _print_usage_table(rows)
    elif args.kind == "dead-skills":
        wl = load_skill_whitelist()
        rows = dead_skills(records, whitelist=wl)
        _print_dead_skills(rows)
    elif args.kind == "channels":
        cb = channel_breakdown(records)
        _print_channels(cb, records)
    return 0


def _print_usage_table(rows: list[dict]) -> None:
    if not rows:
        print("(no skill invocations in metrics.jsonl)")
        return
    print(f"{'skill':30s} {'total':>6s} {'auto':>6s} {'slash':>6s} {'hook':>6s}")
    print("-" * 60)
    for r in rows:
        print(
            f"{r['skill']:30s} {r['total']:>6d} {r['auto']:>6d} "
            f"{r['slash']:>6d} {r['hook']:>6d}"
        )


def _print_dead_skills(rows: list[dict]) -> None:
    if not rows:
        print("(no dead skills — every whitelisted skill has been invoked)")
        return
    auto_dead = [r for r in rows if not r["slash_only"]]
    slash_only = [r for r in rows if r["slash_only"]]
    if auto_dead:
        print("# Dead skills (description routing never fired):")
        for r in auto_dead:
            print(f"  - {r['skill']}")
    if slash_only:
        print("# Slash-only skills never invoked (auto-trigger disabled by design):")
        for r in slash_only:
            print(f"  - {r['skill']}")


def _print_channels(cb: dict[str, int], records: list[dict]) -> None:
    print(f"sessions analyzed: {len(records)}")
    total = sum(cb.values()) or 1
    for ch in ("auto", "slash", "hook"):
        n = cb.get(ch, 0)
        pct = (n / total) * 100
        print(f"  {ch:6s} {n:>6d}  ({pct:5.1f}%)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent-trace",
        description=(
            "Cross-agent telemetry pipeline. Parses AI coding agent transcripts "
            "into a normalized event stream and surfaces skill usage, channel "
            "breakdown (auto vs slash), and dead-skill detection."
        ),
        epilog=(
            "Examples:\n"
            "  # One-shot backfill of all Claude Code transcripts\n"
            "  agent-trace backfill --adapter claude-code\n"
            "\n"
            "  # Three diagnostic views (no --adapter; reads normalized metrics)\n"
            "  agent-trace report channels       # auto vs slash ratio\n"
            "  agent-trace report usage          # per-skill channel breakdown\n"
            "  agent-trace report dead-skills    # skills never invoked\n"
            "\n"
            "  # Single-file ingest (intended for SessionEnd hook pipelines)\n"
            "  agent-trace ingest --adapter claude-code <transcript.jsonl>\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ingest = sub.add_parser(
        "ingest",
        help="emit one session record from one transcript",
        description=(
            "Parse a single transcript and emit one per-session JSON record to "
            "stdout. Designed to be invoked from a SessionEnd hook:\n"
            "  agent-trace ingest --adapter claude-code \"$TRANSCRIPT\" "
            ">> ~/.claude/metrics.jsonl"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ingest.add_argument("--adapter", required=True, choices=sorted(ADAPTERS))
    ingest.add_argument("transcript", help="path to a single transcript file")
    ingest.set_defaults(func=cmd_ingest)

    backfill = sub.add_parser(
        "backfill",
        help="scan all transcripts for the adapter",
        description=(
            "Walk all known transcripts for the chosen adapter and append one "
            "per-session record to metrics.jsonl. Idempotent — the report "
            "layer deduplicates by session_id at read time."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    backfill.add_argument("--adapter", required=True, choices=sorted(ADAPTERS))
    backfill.add_argument(
        "--out",
        help="metrics.jsonl output path (default: ~/.claude/metrics.jsonl)",
    )
    backfill.set_defaults(func=cmd_backfill)

    report = sub.add_parser(
        "report",
        help="aggregate views over metrics.jsonl",
        description=(
            "Read metrics.jsonl and print one of three diagnostic views. "
            "Does NOT take --adapter — metrics.jsonl is already adapter-"
            "agnostic by construction.\n"
            "\n"
            "  channels      total auto vs slash invocations across sessions\n"
            "  usage         per-skill table with channel split\n"
            "  dead-skills   whitelisted skills that have never been invoked"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    report.add_argument(
        "kind",
        choices=["usage", "dead-skills", "channels"],
        help="which view to print",
    )
    report.add_argument(
        "--metrics",
        help="metrics.jsonl path (default: ~/.claude/metrics.jsonl)",
    )
    report.add_argument(
        "--no-filter",
        action="store_true",
        help="usage report only: include built-ins / unknown names not in the whitelist",
    )
    report.set_defaults(func=cmd_report)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
