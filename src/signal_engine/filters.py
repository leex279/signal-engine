"""Stage 3: Factual code filters (age, engagement floor, language, length)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import re

from signal_engine.models import SignalItem
from signal_engine.store import SignalStore

COMMUNITY_SOURCES = {"hacker-news", "reddit"}
CHANGELOG_SOURCES = {
    "claude-code",
    "gemini-cli",
    "hyperframes",
    "openai-codex",
    "coleam00-skills",
    "ollama",
}


def is_mostly_english(text: str) -> bool:
    """Return True if the text is predominantly ASCII/Latin characters."""
    if not text:
        return True
    non_space = [ch for ch in text if not ch.isspace()]
    if not non_space:
        return True
    # Count CJK, Cyrillic, Arabic, Hangul characters
    non_latin = sum(
        1
        for ch in non_space
        if (
            "\u0400" <= ch <= "\u04ff"  # Cyrillic
            or "\u0600" <= ch <= "\u06ff"  # Arabic
            or "\u3040" <= ch <= "\u30ff"  # Hiragana/Katakana
            or "\u4e00" <= ch <= "\u9fff"  # CJK
            or "\uac00" <= ch <= "\ud7af"  # Hangul
        )
    )
    return (non_latin / len(non_space)) < 0.20


def run_code_filters(
    store: SignalStore,
    max_age_hours: float = 48.0,
    changelog_seed_days: float = 7.0,
    min_community_engagement: float = 15.0,
) -> dict[str, int]:
    """Run factual code filters on all unfiltered items in the store and record drop reasons."""
    now = datetime.now(timezone.utc)
    community_cutoff = now - timedelta(hours=max_age_hours)
    changelog_cutoff = now - timedelta(days=changelog_seed_days)

    items = store.get_unfiltered_items()
    counts: Counter[str] = Counter()
    counts["total_evaluated"] = len(items)

    for item in items:
        # 1. Age filter
        if item.published_at is not None:
            cutoff = (
                changelog_cutoff
                if item.source in CHANGELOG_SOURCES
                else community_cutoff
            )
            if item.published_at < cutoff:
                store.mark_filtered(item.id, "age")
                counts["dropped_age"] += 1
                continue
        else:
            # Undated changelog items from deep down a file are historical
            if item.source in CHANGELOG_SOURCES:
                store.mark_filtered(item.id, "age_undated")
                counts["dropped_age"] += 1
                continue

        # 2. Engagement floor for community sources
        if item.source in COMMUNITY_SOURCES:
            eng = item.engagement if item.engagement is not None else 0.0
            if eng < min_community_engagement:
                store.mark_filtered(item.id, "engagement_floor")
                counts["dropped_engagement"] += 1
                continue

        # 3. Language filter (English only)
        combined = f"{item.title} {item.body[:500]}"
        if not is_mostly_english(combined):
            store.mark_filtered(item.id, "language")
            counts["dropped_language"] += 1
            continue

        # 4. Minimum content/title sanity filter
        clean_title = re.sub(r"^\[[^\]]+\]\s*", "", item.title).strip()
        if len(clean_title) < 8:
            store.mark_filtered(item.id, "too_short")
            counts["dropped_short"] += 1
            continue

        counts["survived"] += 1

    return dict(counts)
