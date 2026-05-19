"""agent-trace 命令列介面。

子命令:
  ingest    解析單一 transcript,將該 session 的 record 寫到 stdout
  backfill  掃描指定 adapter 的所有 transcript,附加到 metrics.jsonl
  report    彙整 metrics.jsonl,印出 usage / dead-skill / channel 視圖
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
            "跨 agent telemetry pipeline。將 AI coding agent 的 transcript "
            "解析成正規化事件流,輸出 skill 使用量、channel 分布 (auto vs "
            "slash) 與 dead-skill 偵測。"
        ),
        epilog=(
            "範例:\n"
            "  # 一次性把所有 Claude Code transcript 灌入 metrics.jsonl\n"
            "  agent-trace backfill --adapter claude-code\n"
            "\n"
            "  # 三種診斷視圖 (不需要 --adapter,直接讀正規化資料)\n"
            "  agent-trace report channels       # auto vs slash 比例\n"
            "  agent-trace report usage          # 每個 skill 的 channel 拆解\n"
            "  agent-trace report dead-skills    # 從未被觸發的 skill\n"
            "\n"
            "  # 單檔 ingest (設計給 SessionEnd hook 串接)\n"
            "  agent-trace ingest --adapter claude-code <transcript.jsonl>\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ingest = sub.add_parser(
        "ingest",
        help="從單一 transcript 輸出一筆 session record",
        description=(
            "解析單一 transcript,將該 session 的 JSON record 寫到 stdout。"
            "設計上預期由 SessionEnd hook 觸發:\n"
            "  agent-trace ingest --adapter claude-code \"$TRANSCRIPT\" "
            ">> ~/.claude/metrics.jsonl"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ingest.add_argument("--adapter", required=True, choices=sorted(ADAPTERS))
    ingest.add_argument("transcript", help="單一 transcript 檔案路徑")
    ingest.set_defaults(func=cmd_ingest)

    backfill = sub.add_parser(
        "backfill",
        help="掃描該 adapter 的所有 transcript",
        description=(
            "走訪指定 adapter 所有已知的 transcript,把每個 session 的 "
            "record 附加到 metrics.jsonl。具備冪等性—report 層在讀取時"
            "會依 session_id 去重。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    backfill.add_argument("--adapter", required=True, choices=sorted(ADAPTERS))
    backfill.add_argument(
        "--out",
        help="metrics.jsonl 輸出路徑 (預設: ~/.claude/metrics.jsonl)",
    )
    backfill.set_defaults(func=cmd_backfill)

    report = sub.add_parser(
        "report",
        help="從 metrics.jsonl 產出彙整視圖",
        description=(
            "讀取 metrics.jsonl 並印出三種診斷視圖之一。不接受 --adapter "
            "—metrics.jsonl 本身已經是 adapter-agnostic 的正規化資料。\n"
            "\n"
            "  channels      所有 session 的 auto vs slash 總計\n"
            "  usage         每個 skill 的使用次數及 channel 拆解表格\n"
            "  dead-skills   whitelist 內從未被觸發過的 skill"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    report.add_argument(
        "kind",
        choices=["usage", "dead-skills", "channels"],
        help="要印出哪一種視圖",
    )
    report.add_argument(
        "--metrics",
        help="metrics.jsonl 路徑 (預設: ~/.claude/metrics.jsonl)",
    )
    report.add_argument(
        "--no-filter",
        action="store_true",
        help="只用於 usage 視圖: 連同 whitelist 外的內建/未知名稱也一併列出",
    )
    report.set_defaults(func=cmd_report)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
