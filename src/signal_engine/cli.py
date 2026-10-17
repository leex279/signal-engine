"""Command-line entry point for the Signal Engine."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv

from signal_engine.store import SignalStore
from signal_engine.sources.github_and_changelogs import fetch_claude_code


def configure_utf8() -> None:
    """Force UTF-8 stdout/stderr on Windows so emoji and non-ASCII titles never crash."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def cmd_stage1(db_path: str) -> None:
    store = SignalStore(db_path)
    try:
        items = fetch_claude_code()
        fetched_1, new_1 = store.upsert_items("claude-code", items)
        items_2 = fetch_claude_code()
        fetched_2, new_2 = store.upsert_items("claude-code", items_2)
        print(
            f"Stage 1 (claude-code) -> Run 1: {fetched_1} fetched, {new_1} stored | "
            f"Run 2 (dedupe proof): {fetched_2} fetched, {new_2} new stored"
        )
        for sample in items[:3]:
            print(f"  - [{sample.id}] {sample.title} ({sample.url})")
    finally:
        store.close()


def main() -> None:
    configure_utf8()
    load_dotenv()
    parser = argparse.ArgumentParser(prog="signal-engine")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("stage1", help="Run Stage 1 single-source proof")
    p1.add_argument("--db", default="data/test_stage1.db", help="SQLite DB path")

    args = parser.parse_args()
    if args.cmd == "stage1":
        cmd_stage1(args.db)


if __name__ == "__main__":
    main()
