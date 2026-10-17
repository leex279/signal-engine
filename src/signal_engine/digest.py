"""Stage 5: Reading pass, version collapsing, per-repo quotas, video candidates, and Obsidian delivery."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import time
from typing import Any
import httpx

from signal_engine.enrichment import OBSIDIAN_SIGNALS_DIR, enrich_surviving_items
from signal_engine.models import SignalItem


DIGEST_SYSTEM_PROMPT = """You are the video-topic editor for one YouTube creator ("DIY Smart Code": developers, hobbyists and small businesses; Claude Code power user; Windows PC with an AMD 7900 XTX, NOT a Mac).
The creator reads this every morning to decide WHAT VIDEO TO MAKE NEXT. Repo maintenance is secondary.

You receive:
- `channel_winners`: the creator's own best-performing videos (real view counts). Match new topics against these patterns.
- `video_pool`: items scored as possible video topics (already tagged with `catalog_status`, `competitor_flag`, `cross_source_count`).
- `stack_pool`: releases in the creator's own stack worth knowing about.
- `also_pool`: everything else that passed filters.
- `stack_summary`: HyperFrames pin drift and breaking changes.

Proven formats (rank by these): (1) money / usage-limit / pricing / plan change that costs viewers something, (2) model launch the creator can test head-to-head, (3) X vs Y debate with two named camps, (4) hidden flag / env-var / docs trick most people do not know, (5) new viral repo/skill that can be run and tested on Windows.
Plain version bumps and bugfixes are NOT video topics.

Strict rules:
- **Top Video Picks: 3 to 5 picks, ranked, best first. One pick per topic: merge items about the same story (e.g. two threads on the same plan's limits) into a single pick and cite both sources.** Never pad: if only 2 items are really good, list 2. Skip items whose `catalog_status` starts with "already covered" (list them in one line under `Already covered` instead). Never pick datacenter-only hardware topics as a "run it yourself" video; frame them as "what this means for you" or skip.
- Each pick needs: a concrete hook line in the creator's voice (loss/money framing, "most people don't know", or a named X vs Y; honest, no hype), a format (Short / Long / Debate Long), the proof to capture (what to run or measure on their own machine, using real evidence), a one-line `Why now`, and the dedup status. Preserve `competitor_flag` verbatim and say what the creator's own angle should be.
- Never invent hardware, tools, models, benchmarks, results or links. Use only facts in the items; never attribute a spec to the wrong model (check each number against the item that states it); only name rival models that appear in the pools or the creator's own catalog.
- **Hardware reality (24 GB VRAM):** the creator's GPU holds roughly 30B dense / 35B-active-class quantized models. Anything larger (e.g. a 100B+ MoE) cannot be tested locally; propose a hosted/cloud test (OpenRouter, Ollama cloud) or a "what it means for you" angle instead of a local run.
- **Wikilinks:** write `[[slug]]` ONLY when a pool item carries that exact `catalog_slug`. Never invent a slug. Items with `catalog_status` "new topic" are NOT covered. If you cannot name a specific test to run, the item is not a pick.
- **Stack updates:** max 4 bullets, never repeating an item already covered by a pick or listed under `Already covered`, one per tool, only things that change how the creator works or videos (new flags, env-vars, breaking changes, limit/outage changes). Collapse version ranges. Skip routine bumps.
- **Action for my repo:** from `stack_summary` only (pin drift with upgrade command, breaking changes). Omit the section if both are empty.
- Also seen: max 5 one-liners, each with a link. No hype words, no exclamation marks. Keep every link.

Format:
# <YYYY-MM-DD> - <one line: the single best video topic today>

## Top Video Picks
1. **<Working title>** - `<Short | Long | Debate Long>` `[new topic]` (+ `[competitor covered (Name): needs own angle]` if present)
   - **Hook:** <one line>
   - **Proof to capture:** <what to run / measure / screenshot>
   - **Why now:** <one line, with the source fact>
   - [source](url)

## Stack updates
- **<Tool & version range>** - 1-2 sentences on what changes for the creator. [source](url)

## Action for my repo
- **HyperFrames pin drift:** <pinned vs latest, N releases behind, upgrade command>
- <breaking change, if any>

## Already covered / skipped
- One line: `[[slug]]` topics that were in the news but are already on the channel.

## Also seen
- One-liner with [source](url)
"""


CORE_STACK_SOURCES = {
    "claude-code",
    "claude-apps",
    "antigravity-cursor-browseros",
    "gemini-cli",
    "hyperframes",
    "openai-codex",
    "coleam00-skills",
    "video-toolchain",
}


def load_channel_winners(limit: int = 12) -> list[dict[str, Any]]:
    """Top published videos by real view count from the Obsidian catalog (what actually works for the channel)."""
    from signal_engine.enrichment import FALLBACK_CATALOG_PATH, OBSIDIAN_CATALOG_PATH

    for path in (OBSIDIAN_CATALOG_PATH, FALLBACK_CATALOG_PATH):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue
        videos = data.get("videos", data) if isinstance(data, dict) else data
        scored = [
            {
                "title": v.get("title_published") or v.get("slug"),
                "views": (v.get("stats") or {}).get("views") or 0,
                "format": v.get("format"),
            }
            for v in videos
            if isinstance(v, dict) and ((v.get("stats") or {}).get("views") or 0) > 0
        ]
        scored.sort(key=lambda x: x["views"], reverse=True)
        return scored[:limit]
    return []


def _strip_unknown_wikilinks(markdown: str, known_slugs: set[str]) -> str:
    """Turn `[[slug]]` into plain `slug` when the slug is not a real catalog or tracker entry."""

    def _fix(m: re.Match[str]) -> str:
        slug = m.group(1).split("|")[0].strip()
        return m.group(0) if slug in known_slugs else slug

    return re.sub(r"\[\[([^\]]+)\]\]", _fix, markdown)


def _payload_row(it: SignalItem, repo_key: str, excerpt_len: int = 320) -> dict[str, Any]:
    dec = it.decision or {}
    meta = it.metadata or {}
    return {
        "id": it.id,
        "source": it.source,
        "repo_or_channel": repo_key,
        "title": it.title,
        "url": it.url,
        "published_at": it.published_at.strftime("%Y-%m-%d %H:%M UTC") if it.published_at else None,
        "excerpt": (it.body or "")[:excerpt_len],
        "relevance": dec.get("relevance", 0.5),
        "video_level": dec.get("video_level", 1.0),
        "catalog_status": meta.get("catalog_status", "new topic"),
        "catalog_slug": meta.get("catalog_slug"),
        "competitor_flag": meta.get("competitor_flag"),
        "breaking_change": meta.get("breaking_change", False),
        "cross_source_count": meta.get("cross_source_count", 1),
    }


def collapse_and_select_candidates(
    items: list[SignalItem],
    max_video: int = 14,
    max_stack: int = 6,
    max_also: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    """Split survivors into a video-topic pool (ranked first), a collapsed stack-updates pool, and an also-seen pool."""
    live = [it for it in items if (it.decision or {}).get("route") != "drop"]

    def _repo(it: SignalItem) -> str:
        return (it.metadata or {}).get("repo") or it.source

    def _video_key(it: SignalItem) -> tuple[float, int, float]:
        dec = it.decision or {}
        return (
            float(dec.get("video_level", 1.0)),
            int((it.metadata or {}).get("cross_source_count", 1)),
            float(dec.get("relevance", 0.5)),
        )

    video_items = sorted(
        (it for it in live if float((it.decision or {}).get("video_level", 1.0)) >= 2.0),
        key=_video_key,
        reverse=True,
    )[:max_video]
    used = {it.id for it in video_items}

    # Stack updates: best keep-routed item per core-stack repo, collapsing sibling releases into the excerpt.
    by_repo: dict[str, list[SignalItem]] = {}
    for it in live:
        if it.id in used or it.source not in CORE_STACK_SOURCES:
            continue
        by_repo.setdefault(_repo(it), []).append(it)

    stack_rows: list[dict[str, Any]] = []
    for repo_key, group in by_repo.items():
        group.sort(
            key=lambda x: (
                1 if (x.decision or {}).get("route") == "keep" else 0,
                float((x.decision or {}).get("relevance", 0.5)),
            ),
            reverse=True,
        )
        top = group[0]
        if float((top.decision or {}).get("relevance", 0.5)) < 0.75:
            continue
        row = _payload_row(top, repo_key, excerpt_len=500)
        if len(group) > 1:
            row["also_in_range"] = "; ".join(g.title[:80] for g in group[1:5])
        stack_rows.append(row)
        used.update(g.id for g in group)
    stack_rows.sort(key=lambda r: (r["breaking_change"], float(r["relevance"])), reverse=True)
    stack_rows = stack_rows[:max_stack]

    also_items = sorted(
        (it for it in live if it.id not in used),
        key=lambda x: float((x.decision or {}).get("relevance", 0.5)),
        reverse=True,
    )[:max_also]

    return {
        "video_pool": [_payload_row(it, _repo(it)) for it in video_items],
        "stack_pool": stack_rows,
        "also_pool": [_payload_row(it, _repo(it), excerpt_len=160) for it in also_items],
    }


def generate_digest(
    items: list[SignalItem],
    digest_date: str | None = None,
    model: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Enrich surviving items, run the single LLM reading pass, and return (markdown_text, usage_stats)."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set in .env. Please add it to your .env file."
        )

    reading_model = (
        model
        or os.environ.get("READING_MODEL", "anthropic/claude-sonnet-4.5").strip()
    )
    date_str = digest_date or datetime.now().strftime("%Y-%m-%d")

    enriched_items, stack_summary = enrich_surviving_items(items)
    pools = collapse_and_select_candidates(enriched_items)
    compact_items = [row for pool in pools.values() for row in pool]

    user_prompt = (
        f"Today's date: {date_str}\n\n"
        "Channel winners (own best videos by views):\n"
        f"{json.dumps(load_channel_winners(), indent=2, ensure_ascii=False)}\n\n"
        "Stack Summary (Pin Drift & Breaking Changes):\n"
        f"{json.dumps(stack_summary, indent=2, ensure_ascii=False)}\n\n"
        "Pools:\n"
        + json.dumps(pools, indent=2, ensure_ascii=False)
    )

    t0 = time.perf_counter()
    with httpx.Client(timeout=75.0) as client:
        resp = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": reading_model,
                "messages": [
                    {"role": "system", "content": DIGEST_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    elapsed = time.perf_counter() - t0
    content = (data["choices"][0]["message"]["content"] or "").strip()
    known = {row["catalog_slug"] for pool in pools.values() for row in pool if row.get("catalog_slug")}
    content = _strip_unknown_wikilinks(content, known)
    usage = data.get("usage") or {}
    stats = {
        "reading_model": reading_model,
        "items_read": len(compact_items),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "elapsed_sec": round(elapsed, 2),
        "hyperframes_pin_drift": stack_summary.get("hyperframes_pin_drift"),
    }
    return content, stats


def write_digest_file(
    markdown_content: str,
    stats: dict[str, Any],
    digest_dir: str | Path = "digests",
    digest_date: str | None = None,
) -> Path:
    """Write `digests/YYYY-MM-DD.md` in the repo AND mirror to Obsidian `_signals/YYYY-MM-DD.md`."""
    date_str = digest_date or datetime.now().strftime("%Y-%m-%d")
    out_dir = Path(digest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}.md"

    footer = (
        "\n\n---\n"
        f"*Run receipt: {stats.get('items_fetched', '?')} fetched -> "
        f"{stats.get('survived_code_filters', '?')} passed code filters -> "
        f"{stats.get('items_read', '?')} sent to reading pass "
        f"({stats.get('decision_kept', '?')} keep, {stats.get('decision_unsure', '?')} unsure, "
        f"{stats.get('decision_dropped', '?')} dropped) | "
        f"Tokens: {stats.get('total_tokens', '?')} | "
        f"Reading time: {stats.get('elapsed_sec', '?')}s*\n"
    )
    full_text = markdown_content.rstrip() + footer
    out_path.write_text(full_text, encoding="utf-8")

    # Deliver copy to Obsidian Second Brain if drive D: is mounted
    try:
        if OBSIDIAN_SIGNALS_DIR.parent.exists():
            OBSIDIAN_SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
            obsidian_path = OBSIDIAN_SIGNALS_DIR / f"{date_str}.md"
            obsidian_path.write_text(full_text, encoding="utf-8")
    except Exception:
        pass

    return out_path
