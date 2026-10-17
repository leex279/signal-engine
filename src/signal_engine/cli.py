"""Command-line entry point for the Signal Engine."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import os
import sys
import time
from dotenv import load_dotenv

from signal_engine.store import SignalStore
from signal_engine.sources import ALL_SOURCES
from signal_engine.sources.github_and_changelogs import fetch_claude_code
from signal_engine.filters import run_code_filters
from signal_engine.decisions import INTERVIEW_EXAMPLES, score_items_parallel
from signal_engine.digest import generate_digest, write_digest_file


def configure_utf8() -> None:
    """Force UTF-8 stdout/stderr on Windows so emoji and non-ASCII titles never crash."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def cmd_check_env() -> None:
    """Safely check whether keys are set without ever printing their values."""
    for key_name in ("OPENROUTER_API_KEY", "GITHUB_TOKEN"):
        val = os.environ.get(key_name, "").strip()
        is_set = bool(val and not val.startswith("your_"))
        print(f"{key_name}: {'SET' if is_set else 'NOT_SET'}")


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
    finally:
        store.close()


def cmd_stage2(db_path: str) -> None:
    store = SignalStore(db_path)
    try:
        total_fetched = 0
        total_new_run1 = 0
        total_new_run2 = 0
        for name, method_desc, fetcher in ALL_SOURCES:
            items1 = fetcher()
            f1, n1 = store.upsert_items(name, items1)
            items2 = fetcher()
            f2, n2 = store.upsert_items(name, items2)
            total_fetched += f1
            total_new_run1 += n1
            total_new_run2 += n2
            print(
                f"{name:18s} | {method_desc:46s} | returned={f1:3d} | stored={n1:3d} | rerun_new={n2:2d}"
            )
        print(
            f"TOTAL              | 10 sources ($0.00 cost)                        | returned={total_fetched:3d} | stored={total_new_run1:3d} | rerun_new={total_new_run2:2d}"
        )
    finally:
        store.close()


def cmd_stage3(db_path: str) -> None:
    store = SignalStore(db_path)
    try:
        store.reset_filters_and_decisions()
        stats = run_code_filters(store)
        print(
            f"Stage 3 filters -> evaluated={stats.get('total_evaluated', 0)} | "
            f"dropped_age={stats.get('dropped_age', 0)} | "
            f"dropped_engagement={stats.get('dropped_engagement', 0)} | "
            f"dropped_language={stats.get('dropped_language', 0)} | "
            f"dropped_short={stats.get('dropped_short', 0)} | "
            f"survived={stats.get('survived', 0)}"
        )
        surviving = store.get_unfiltered_items()
        for idx, it in enumerate(surviving[:20], 1):
            eng_str = f" ({int(it.engagement)} pts)" if it.engagement is not None else ""
            print(f"  {idx:2d}. [{it.source}]{eng_str} {it.title}")
    finally:
        store.close()


def cmd_stage4(db_path: str) -> None:
    store = SignalStore(db_path)
    try:
        # 1. Score the interview keep/drop benchmark examples
        example_items = [it for _, it in INTERVIEW_EXAMPLES]
        ex_results, ex_elapsed = asyncio.run(score_items_parallel(example_items))
        misses = 0
        print(f"--- Interview Benchmark Examples ({len(example_items)} items, {ex_elapsed:.2f}s) ---")
        for (expected, _), (it, dec) in zip(INTERVIEW_EXAMPLES, ex_results):
            route = dec.get("route", "unsure")
            matched = (expected == "keep" and route in ("keep", "unsure")) or (
                expected == "drop" and route == "drop"
            )
            if not matched:
                misses += 1
            verdict = "OK" if matched else "MISS"
            print(
                f"  [{verdict}] expected={expected:4s} route={route:6s} "
                f"(rel={dec.get('relevance'):.2f}, new={dec.get('new'):.2f}, model={dec.get('model')}) | {it.title[:80]}"
            )
        print(f"Benchmark misses: {misses}/{len(example_items)}")

        # 2. Score today's real surviving items in the DB
        surviving = store.get_unfiltered_items()
        if not surviving:
            print("No surviving items in DB. Run stage2 and stage3 first.")
            return

        real_results, real_elapsed = asyncio.run(score_items_parallel(surviving))
        counts = {"keep": 0, "unsure": 0, "drop": 0}
        for it, dec in real_results:
            route = dec.get("route", "unsure")
            counts[route] = counts.get(route, 0) + 1
            filtered_by = "decision_drop" if route == "drop" else None
            store.save_decision(it.id, dec, filtered_by=filtered_by)

        print(
            f"Stage 4 real items ({len(surviving)} scored in {real_elapsed:.2f}s) -> "
            f"keep={counts['keep']} | unsure={counts['unsure']} | drop={counts['drop']}"
        )
        print("--- Sample Kept Items ---")
        for it, dec in [r for r in real_results if r[1].get("route") == "keep"][:8]:
            print(f"  [KEEP rel={dec['relevance']:.2f} new={dec['new']:.2f}] [{it.source}] {it.title[:90]}")
        print("--- Sample Dropped Items ---")
        for it, dec in [r for r in real_results if r[1].get("route") == "drop"][:8]:
            print(f"  [DROP rel={dec['relevance']:.2f} new={dec['new']:.2f}] [{it.source}] {it.title[:90]}")
    finally:
        store.close()


def cmd_stage5(db_path: str, digest_dir: str) -> None:
    store = SignalStore(db_path)
    try:
        all_items = store.get_all_items()
        candidates = store.get_surviving_for_reading()
        if not candidates:
            print("No surviving items for reading pass.")
            return

        md_text, reading_stats = generate_digest(candidates)
        dec_kept = sum(1 for it in candidates if (it.decision or {}).get("route") == "keep")
        dec_unsure = sum(1 for it in candidates if (it.decision or {}).get("route") != "keep")
        dec_dropped = sum(1 for it in all_items if it.filtered_by == "decision_drop")
        code_survived = len(candidates) + dec_dropped

        full_stats = {
            **reading_stats,
            "items_fetched": len(all_items),
            "survived_code_filters": code_survived,
            "decision_kept": dec_kept,
            "decision_unsure": dec_unsure,
            "decision_dropped": dec_dropped,
        }
        out_path = write_digest_file(md_text, full_stats, digest_dir=digest_dir)
        print(
            f"Stage 5 digest written to {out_path} | "
            f"read={reading_stats['items_read']} items | "
            f"tokens={reading_stats['total_tokens']} | "
            f"elapsed={reading_stats['elapsed_sec']}s"
        )
    finally:
        store.close()


def cmd_run(db_path: str, digest_dir: str) -> None:
    """Full daily pipeline run: fetch -> store -> code filters -> decision pass -> digest."""
    started_iso = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    store = SignalStore(db_path)
    try:
        total_fetched = 0
        total_new = 0
        source_stats: dict[str, dict[str, int]] = {}
        for name, _, fetcher in ALL_SOURCES:
            items = fetcher()
            f_cnt, n_cnt = store.upsert_items(name, items)
            total_fetched += f_cnt
            total_new += n_cnt
            source_stats[name] = {"fetched": f_cnt, "new": n_cnt}

        filter_stats = run_code_filters(store)
        surviving = store.get_unfiltered_items()

        dec_counts = {"keep": 0, "unsure": 0, "drop": 0}
        dec_elapsed = 0.0
        if surviving:
            scored, dec_elapsed = asyncio.run(score_items_parallel(surviving))
            for it, dec in scored:
                route = dec.get("route", "unsure")
                dec_counts[route] = dec_counts.get(route, 0) + 1
                filtered_by = "decision_drop" if route == "drop" else None
                store.save_decision(it.id, dec, filtered_by=filtered_by)

        candidates = store.get_surviving_for_reading()
        date_str = datetime.now().strftime("%Y-%m-%d")
        if candidates:
            md_text, reading_stats = generate_digest(candidates, digest_date=date_str)
        else:
            md_text = f"# {date_str} - No new high-signal items today\n\nNo new items passed filters today.\n"
            reading_stats = {"items_read": 0, "total_tokens": 0, "elapsed_sec": 0.0}

        full_stats = {
            **reading_stats,
            "items_fetched": total_fetched,
            "items_new": total_new,
            "survived_code_filters": filter_stats.get("survived", 0),
            "decision_kept": dec_counts["keep"],
            "decision_unsure": dec_counts["unsure"],
            "decision_dropped": dec_counts["drop"],
            "decision_elapsed_sec": round(dec_elapsed, 2),
            "wall_time_sec": round(time.perf_counter() - t0, 2),
            "sources": source_stats,
            "filters": filter_stats,
        }
        out_path = write_digest_file(md_text, full_stats, digest_dir=digest_dir, digest_date=date_str)
        store.mark_in_digest([it.id for it in candidates], date_str)
        store.log_run(started_iso, full_stats)
        print(
            f"Run complete in {full_stats['wall_time_sec']}s -> {out_path} | "
            f"fetched={total_fetched} (new={total_new}) -> "
            f"code_survived={full_stats['survived_code_filters']} -> "
            f"read={reading_stats['items_read']} (keep={dec_counts['keep']}, unsure={dec_counts['unsure']}, drop={dec_counts['drop']})"
        )
    finally:
        store.close()


def cmd_measure_decision(db_path: str) -> None:
    """Compare reading pass with Decision Pass OFF vs ON on the same code-filtered rows."""
    store = SignalStore(db_path)
    try:
        all_items = store.get_all_items()
        code_survivors = [
            it
            for it in all_items
            if it.filtered_by is None or it.filtered_by == "decision_drop"
        ]
        decision_survivors = [it for it in all_items if it.filtered_by is None]
        dropped_by_decision = [
            it for it in all_items if it.filtered_by == "decision_drop"
        ]

        # Run 1: Decision pass OFF (pass all code survivors with high max_per_source)
        md_off, stats_off = generate_digest(code_survivors)
        # Run 2: Decision pass ON (pass only decision survivors)
        md_on, stats_on = generate_digest(decision_survivors)

        missed_by_drop = [
            it.title
            for it in dropped_by_decision
            if it.url and it.url in md_off
        ]
        print(
            f"Decision Pass OFF -> items_candidates={len(code_survivors)} (sent={stats_off['items_read']}) | "
            f"tokens={stats_off['total_tokens']} | time={stats_off['elapsed_sec']}s"
        )
        print(
            f"Decision Pass ON  -> items_candidates={len(decision_survivors)} (sent={stats_on['items_read']}) | "
            f"tokens={stats_on['total_tokens']} | time={stats_on['elapsed_sec']}s"
        )
        print(
            f"Items dropped by decision pass that LLM would have included: {len(missed_by_drop)}"
        )
        for m in missed_by_drop:
            print(f"  - {m}")
    finally:
        store.close()


def main() -> None:
    configure_utf8()
    load_dotenv()
    parser = argparse.ArgumentParser(prog="signal-engine")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check-env", help="Safely check whether environment keys are set")

    p1 = sub.add_parser("stage1", help="Run Stage 1 single-source proof")
    p1.add_argument("--db", default="data/test_stage1.db", help="SQLite DB path")

    p2 = sub.add_parser("stage2", help="Run Stage 2 all-sources fetch + dedupe proof")
    p2.add_argument("--db", default="data/test_pipeline.db", help="SQLite DB path")

    p3 = sub.add_parser("stage3", help="Run Stage 3 code filters on stored items")
    p3.add_argument("--db", default="data/test_pipeline.db", help="SQLite DB path")

    p4 = sub.add_parser("stage4", help="Run Stage 4 decision pass proof")
    p4.add_argument("--db", default="data/test_pipeline.db", help="SQLite DB path")

    p5 = sub.add_parser("stage5", help="Run Stage 5 reading pass and write digest")
    p5.add_argument("--db", default="data/test_pipeline.db", help="SQLite DB path")
    p5.add_argument("--out", default="digests", help="Digest output directory")

    pm = sub.add_parser("measure-decision", help="Compare reading pass with and without decision pass")
    pm.add_argument("--db", default="data/test_pipeline.db", help="SQLite DB path")

    prun = sub.add_parser("run", help="Run full daily pipeline")
    prun.add_argument("--db", default="data/signal.db", help="SQLite DB path")
    prun.add_argument("--out", default="digests", help="Digest output directory")

    args = parser.parse_args()
    if args.cmd == "check-env":
        cmd_check_env()
    elif args.cmd == "stage1":
        cmd_stage1(args.db)
    elif args.cmd == "stage2":
        cmd_stage2(args.db)
    elif args.cmd == "stage3":
        cmd_stage3(args.db)
    elif args.cmd == "stage4":
        cmd_stage4(args.db)
    elif args.cmd == "stage5":
        cmd_stage5(args.db, args.out)
    elif args.cmd == "measure-decision":
        cmd_measure_decision(args.db)
    elif args.cmd == "run":
        cmd_run(args.db, args.out)


if __name__ == "__main__":
    main()
