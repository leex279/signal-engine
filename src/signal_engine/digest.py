"""Stage 5: Reading pass, version collapsing, per-repo quotas, video candidates, and Obsidian delivery."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import time
from typing import Any
import httpx

from signal_engine.enrichment import OBSIDIAN_SIGNALS_DIR, enrich_surviving_items
from signal_engine.models import SignalItem


DIGEST_SYSTEM_PROMPT = """You write a daily signal digest for one AI engineer and YouTube creator ("DIY Smart Code").
They keep up with releases, changelogs, flags/env-vars, skills, workflows, and models across their stack:
Google Antigravity, Gemini CLI/API/Gemma, Anthropic Claude Code/API, HeyGen HyperFrames, OpenAI Codex, Cursor, BrowserOS, MCP, ElevenLabs, GSAP, n8n, and local LLMs (Ollama / llama.cpp / ROCm).

Below are today's filtered, enriched items, plus a `stack_summary` object (showing their HyperFrames pin drift and any breaking changes).

Strict Rules:
- **Enforce the 10-item cap across the two main sections** (`Releases & Changelogs` + `Agent Workflows, Repos & Models` combined <= 10 bullets total).
- **Per-repo quota & version collapsing:** At most 2 bullets per product/repo in `Releases & Changelogs`. If multiple versions of the same tool shipped (e.g. Claude Code v2.1.299–v2.1.302, or HyperFrames v0.8.160–v0.8.167), collapse them into 1–2 consolidated bullets covering the best flags/features.
- **Reserve at least 3 slots** in `Agent Workflows, Repos & Models` for community workflows, viral repos, new models (OpenRouter/HF/Ollama), or engineering blog findings. Never let `Agent Workflows, Repos & Models` come out empty when community/model items are present.
- **Video Candidates section (up to 4 bullets):** Pick the highest `video_level` items (hidden CLI flags/env-vars, usage-limit/cost angles, X vs Y debates, viral skills/repos, or local GPU benchmarks). Preserve each item's `catalog_status` tag (`[new topic]` or `[already covered: [[slug]]]`) and `competitor_flag` (`[competitor covered: needs own angle]`) verbatim!
- **Action for my repo section:** Always start with 1–2 bullets summarizing the `stack_summary` (e.g. HyperFrames pin drift in `diy-yt-creator-hyperframes/package.json` and any breaking changes).
- One or two plain sentences per entry: what changed, and why it matters.
- Keep every link. Never invent a link or detail not in the item.
- No hype words, no exclamation marks.

Format:
# <YYYY-MM-DD> - <one line on what mattered today>

## Action for my repo
- **HyperFrames pin drift:** <pinned vs latest, N releases behind, and upgrade command>
- <Any breaking change or urgent stack action, if present>

## Releases & Changelogs (max 6 bullets, collapse versions per repo)
- **<Tool & version range in plain words>** - 1-2 sentences on the most important flags, features, or changes. [source](url)

## Agent Workflows, Repos & Models (at least 3 bullets, total main <= 10)
- **<Item in plain words>** - 1-2 sentences on what is new and actionable. [source](url)

## Video Candidates (DIY Smart Code)
- **<Hook / angle idea>** (`[new topic]` or `[already covered: [[slug]]]`, plus `[competitor covered ...]` if present) - 1 sentence on the angle (hidden flag, limit/cost angle, debate, or benchmark) and why it works. [source](url)

## Also worth a look (max 4 one-liners)
- One-liner with [source](url)
"""


def collapse_and_select_candidates(
    items: list[SignalItem],
    max_items: int = 60,
    max_per_repo: int = 3,
) -> list[dict[str, Any]]:
    """Collapse same-repo release bursts and cap per-repo items so community, models, and workflows always fit."""
    # Group multiple releases/commits of the same repo into merged summaries if > max_per_repo
    by_repo: dict[str, list[SignalItem]] = {}
    for it in items:
        repo_key = (it.metadata or {}).get("repo") or it.source
        by_repo.setdefault(repo_key, []).append(it)

    payload: list[dict[str, Any]] = []

    # Interleave: take top items per repo/source while respecting max_per_repo
    for repo_key, group in by_repo.items():
        # Sort within group by relevance + video_score
        group.sort(
            key=lambda x: (
                1 if (x.decision or {}).get("route") == "keep" else 0,
                float((x.decision or {}).get("relevance", 0.5)),
                float((x.decision or {}).get("video_score", 0.3)),
            ),
            reverse=True,
        )
        selected = group[:max_per_repo]
        extra = group[max_per_repo : max_per_repo + 4]

        for idx, it in enumerate(selected):
            dec = it.decision or {}
            meta = it.metadata or {}
            excerpt = (it.body or "")[:320]
            if idx == 0 and extra and it.source in ("claude-code", "hyperframes", "gemini-cli", "ollama", "openai-codex"):
                extra_titles = "; ".join(e.title[:80] for e in extra)
                excerpt = f"{excerpt}\n[Also in recent releases for {repo_key}: {extra_titles}]"

            payload.append(
                {
                    "id": it.id,
                    "source": it.source,
                    "repo_or_channel": repo_key,
                    "title": it.title,
                    "url": it.url,
                    "published_at": it.published_at.strftime("%Y-%m-%d %H:%M UTC")
                    if it.published_at
                    else None,
                    "excerpt": excerpt,
                    "decision_route": dec.get("route", "unsure"),
                    "relevance": dec.get("relevance", 0.5),
                    "new_prob": dec.get("new", 0.5),
                    "video_level": dec.get("video_level", 1.0),
                    "catalog_status": meta.get("catalog_status", "new topic"),
                    "competitor_flag": meta.get("competitor_flag"),
                    "breaking_change": meta.get("breaking_change", False),
                    "cross_source_count": meta.get("cross_source_count", 1),
                }
            )

    # Sort final payload so high-relevance and high-video-score items across diverse sources are prominent
    payload.sort(
        key=lambda d: (
            1 if d["decision_route"] == "keep" else 0,
            float(d["relevance"]) + 0.2 * float(d["video_level"]) / 3.0,
        ),
        reverse=True,
    )
    return payload[:max_items]


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
    compact_items = collapse_and_select_candidates(enriched_items)

    user_prompt = (
        f"Today's date: {date_str}\n\n"
        f"Stack Summary (Pin Drift & Breaking Changes):\n"
        f"{json.dumps(stack_summary, indent=2, ensure_ascii=False)}\n\n"
        f"Candidate Items ({len(compact_items)} items across all sources):\n"
        + json.dumps(compact_items, indent=2, ensure_ascii=False)
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
