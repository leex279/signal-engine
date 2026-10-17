"""Stage 5: Reading pass and daily Markdown digest writer."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import time
from typing import Any
import httpx

from signal_engine.models import SignalItem


DIGEST_SYSTEM_PROMPT = """You write a daily digest for one person. They keep up with new releases, changelogs, skills, workflows, and concrete changes in the AI coding agents, models, and video/browser agent tools they use daily (Google Antigravity / Gemini, Anthropic Claude Code / Claude, OpenAI Codex / Cursor, BrowserOS Neo / MCP / Local LLMs like Ollama, and HeyGen HyperFrames), and they read this to decide what to try, adopt, or update in their stack this week.

Below are today's items that passed their filter. Some are marked unsure: include one only if it clearly reports something new and concrete that matters to them.

Rules:
- At most 10 items in the main sections. Pick the ones that change what they would do or try this week.
- Group items about the same release or topic into one entry.
- One or two plain sentences per entry: what changed, and why it matters to their stack.
- Keep every link. Never invent a link or a detail that is not in the item.
- Say plainly when something is a rumor, a minor update, or a deprecation.
- A changelog entry is a launch only if it says something launched.
- No hype words, no exclamation marks.

Format:
# <YYYY-MM-DD> - <one line on what mattered today>

## Releases & Changelogs
- **<Item in plain words>** - 1-2 sentences on what changed and why it matters to your stack. [source](url)

## Agent Workflows, Repos & Models
- **<Item in plain words>** - 1-2 sentences on what is new and actionable. [source](url)

## Also worth a look
- One-liners with [links](url)
"""


def build_reading_payload(
    items: list[SignalItem],
    max_items: int = 65,
    max_per_source: int = 8,
) -> list[dict[str, Any]]:
    """Prepare compact item JSON for the reading pass (keeps first, capped per source so all sources are represented)."""
    payload: list[dict[str, Any]] = []
    per_source_counts: dict[str, int] = {}
    for it in items:
        src_cnt = per_source_counts.get(it.source, 0)
        if src_cnt >= max_per_source:
            continue
        per_source_counts[it.source] = src_cnt + 1
        dec = it.decision or {}
        payload.append(
            {
                "id": it.id,
                "source": it.source,
                "title": it.title,
                "url": it.url,
                "published_at": it.published_at.strftime("%Y-%m-%d %H:%M UTC")
                if it.published_at
                else None,
                "excerpt": (it.body or "")[:350],
                "decision_route": dec.get("route", "unsure"),
                "relevance": dec.get("relevance", 0.5),
                "new_prob": dec.get("new", 0.5),
            }
        )
        if len(payload) >= max_items:
            break
    return payload


def generate_digest(
    items: list[SignalItem],
    digest_date: str | None = None,
    model: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Run the single LLM reading pass and return (markdown_text, usage_stats)."""
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
    compact_items = build_reading_payload(items)

    user_prompt = (
        f"Today's date: {date_str}\n"
        f"Total candidate items ({len(compact_items)}):\n"
        + json.dumps(compact_items, indent=2, ensure_ascii=False)
    )

    t0 = time.perf_counter()
    with httpx.Client(timeout=60.0) as client:
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
    }
    return content, stats


def write_digest_file(
    markdown_content: str,
    stats: dict[str, Any],
    digest_dir: str | Path = "digests",
    digest_date: str | None = None,
) -> Path:
    """Write `digests/YYYY-MM-DD.md` with run receipt footer."""
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
    out_path.write_text(markdown_content.rstrip() + footer, encoding="utf-8")
    return out_path
