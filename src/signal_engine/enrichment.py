"""Video catalog deduplication, competitor tagging, HyperFrames pin-drift, and cross-source boost."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse
import httpx

from signal_engine.models import SignalItem

OBSIDIAN_CATALOG_PATH = Path(
    r"D:\Nextcloud\Obsidian\sync\smartcode\Videos\_catalog\catalog.json"
)
FALLBACK_CATALOG_PATH = Path(
    r"C:\Users\Leex279\Documents\GitHub\diy-yt-creator-hyperframes\.tmp\catalog-publish-check\catalog.json"
)
CLAUDE_BASICS_TRACKER_PATH = Path(
    r"C:\Users\Leex279\Documents\GitHub\diy-yt-creator-hyperframes\templates\shorts\claude-basics\TRACKER.md"
)
HYPERFRAMES_PACKAGE_JSON = Path(
    r"C:\Users\Leex279\Documents\GitHub\diy-yt-creator-hyperframes\package.json"
)
OBSIDIAN_SIGNALS_DIR = Path(
    r"D:\Nextcloud\Obsidian\sync\smartcode\Videos\_signals"
)

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
    "was", "were", "have", "has", "had", "not", "but", "what", "all", "can",
    "out", "use", "using", "how", "why", "new", "now", "more", "into", "over",
    "just", "than", "its", "about", "when", "who", "will", "one", "two", "three",
    "code", "short", "video", "explained", "claude", "ai", "llm", "model", "models",
    "release", "Added", "added", "fix", "feat", "show", "reddit", "youtube",
}

SLUG_NOISE = {"short", "shorts", "long", "explained", "tutorial", "demo", "test", "vs", "v2", "v3", "part", "series", "full"}

BREAKING_RE = re.compile(
    r"\b(deprecat\w*|removed|breaking|renamed|incompatible|migration\s+required)\b",
    re.IGNORECASE,
)


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9_/-]{3,}", (text or "").lower())
    return {w.strip("_-/") for w in words if w.strip("_-/") not in STOPWORDS and len(w) >= 3}


class CatalogMatcher:
    """Matches signal items against the user's 800+ video catalog and Claude Basics tracker."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        cat_path = (
            OBSIDIAN_CATALOG_PATH
            if OBSIDIAN_CATALOG_PATH.exists()
            else FALLBACK_CATALOG_PATH
        )
        if cat_path.exists():
            try:
                data = json.loads(cat_path.read_text(encoding="utf-8"))
                for v in data.get("videos", []):
                    slug = v.get("slug") or ""
                    title = v.get("title_published") or slug
                    if not slug:
                        continue
                    tokens = _tokenize(f"{slug.replace('-', ' ')} {title}")
                    if tokens:
                        self.entries.append(
                            {"slug": slug, "title": title, "tokens": tokens, "source": "catalog"}
                        )
            except Exception:
                pass

        if CLAUDE_BASICS_TRACKER_PATH.exists():
            try:
                for line in CLAUDE_BASICS_TRACKER_PATH.read_text(encoding="utf-8").splitlines():
                    if not line.startswith("|") or "---" in line or "Topic" in line:
                        continue
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 6:
                        topic = parts[3]
                        slug = parts[4]
                        if slug and topic:
                            tokens = _tokenize(f"{slug.replace('-', ' ')} {topic}")
                            self.entries.append(
                                {
                                    "slug": slug,
                                    "title": topic,
                                    "tokens": tokens,
                                    "source": "claude-basics",
                                }
                            )
            except Exception:
                pass

    def match_item(self, item: SignalItem) -> dict[str, Any]:
        """Return best catalog overlap if specific technical tokens match."""
        item_tokens = _tokenize(f"{item.title} {(item.body or '')[:300]}")
        if not item_tokens:
            return {"covered": False, "tag": "new topic", "slug": None}

        best_score = 0.0
        best_entry: dict[str, Any] | None = None
        for entry in self.entries:
            ent_tokens = entry["tokens"]
            if not ent_tokens:
                continue
            overlap = item_tokens & ent_tokens
            if len(overlap) < 2:
                continue
            # Jaccard-like coverage weighted toward the video entry's distinct tokens
            score = len(overlap) / max(len(ent_tokens), 3)
            if score > best_score:
                best_score = score
                best_entry = entry

        # Slug-name match: every distinctive word of a video slug (e.g. reflection-beam-short) appears in the item.
        if best_score < 0.55:
            item_text_tokens = _tokenize(f"{item.title} {(item.body or '')[:600]}")
            for entry in self.entries:
                slug_tokens = _tokenize(entry["slug"].replace("-", " ")) - SLUG_NOISE
                if len(slug_tokens) >= 2 and slug_tokens <= item_text_tokens:
                    best_entry, best_score = entry, 0.9
                    break

        if best_entry and best_score >= 0.55:
            slug = best_entry["slug"]
            return {
                "covered": True,
                "tag": f"already covered: [[{slug}]]",
                "slug": slug,
                "match_score": round(best_score, 2),
            }
        return {"covered": False, "tag": "new topic", "slug": None}


def check_hyperframes_pin_drift() -> dict[str, Any]:
    """Compare diy-yt-creator-hyperframes/package.json pin against latest heygen-com/hyperframes release."""
    pinned_version = None
    if HYPERFRAMES_PACKAGE_JSON.exists():
        try:
            pkg = json.loads(HYPERFRAMES_PACKAGE_JSON.read_text(encoding="utf-8"))
            pinned_version = (pkg.get("devDependencies") or {}).get("hyperframes") or (
                pkg.get("dependencies") or {}
            ).get("hyperframes")
        except Exception:
            pass

    latest_version = None
    releases_behind = 0
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(
                "https://api.github.com/repos/heygen-com/hyperframes/releases",
                params={"per_page": 30},
                headers={"User-Agent": "signal-engine/0.2.0"},
            )
            if resp.status_code == 200:
                rels = resp.json()
                if rels:
                    latest_version = (rels[0].get("tag_name") or "").lstrip("v")
                    if pinned_version:
                        clean_pin = pinned_version.lstrip("^~v")
                        try:
                            pin_minor_patch = [int(x) for x in clean_pin.split(".")]
                            lat_minor_patch = [int(x) for x in latest_version.split(".")]
                            if (
                                len(pin_minor_patch) == 3
                                and len(lat_minor_patch) == 3
                                and pin_minor_patch[:2] == lat_minor_patch[:2]
                            ):
                                releases_behind = max(0, lat_minor_patch[2] - pin_minor_patch[2])
                        except Exception:
                            pass
    except Exception:
        pass

    return {
        "pinned_version": pinned_version,
        "latest_version": latest_version,
        "releases_behind": releases_behind,
        "upgrade_cmd": "npx hyperframes upgrade --project",
    }


def enrich_surviving_items(items: list[SignalItem]) -> tuple[list[SignalItem], dict[str, Any]]:
    """Enrich surviving items with:
    1. Catalog & Claude Basics deduplication (`already covered: [[slug]]` vs `new topic`)
    2. Competitor coverage detection (Cloud Codes / The Stack ai)
    3. Breaking-change stack impact tags
    4. Cross-source URL/repo mention boost
    """
    matcher = CatalogMatcher()

    # Collect competitor video tokens from today's store
    competitor_items = [
        it
        for it in items
        if it.source == "youtube-creators"
        and (it.metadata or {}).get("is_competitor")
    ]
    competitor_token_sets = [
        (
            (it.metadata or {}).get("creator", "Competitor"),
            _tokenize(f"{it.title} {(it.body or '')[:200]}"),
        )
        for it in competitor_items
    ]

    # Count URL domains/paths and GitHub repo references across sources for cross-source boost
    url_sources: dict[str, set[str]] = {}
    for it in items:
        norm_url = _normalize_url(it.url)
        if norm_url:
            url_sources.setdefault(norm_url, set()).add(it.source)

    breaking_items: list[str] = []

    for it in items:
        meta = dict(it.metadata or {})

        # 1. Catalog match
        cat_match = matcher.match_item(it)
        meta["catalog_status"] = cat_match["tag"]
        meta["catalog_slug"] = cat_match["slug"]

        # 2. Competitor coverage flag
        if meta.get("is_competitor"):
            creator = meta.get("creator", "Competitor")
            meta["competitor_flag"] = f"competitor video ({creator}): needs own angle"
        else:
            it_tokens = _tokenize(it.title)
            for comp_name, comp_tokens in competitor_token_sets:
                if len(it_tokens & comp_tokens) >= 2:
                    meta["competitor_flag"] = f"competitor covered ({comp_name}): needs own angle"
                    break

        # 3. Breaking change check
        if BREAKING_RE.search(f"{it.title} {(it.body or '')[:600]}"):
            meta["breaking_change"] = True
            breaking_items.append(f"[{it.source}] {it.title[:90]}")

        # 4. Cross-source boost
        norm_url = _normalize_url(it.url)
        if norm_url and len(url_sources.get(norm_url, set())) > 1:
            meta["cross_source_count"] = len(url_sources[norm_url])
            if it.decision:
                it.decision["relevance"] = min(
                    1.0, round(float(it.decision.get("relevance", 0.5)) + 0.15, 3)
                )

        it.metadata = meta

    pin_drift = check_hyperframes_pin_drift()
    stack_summary = {
        "hyperframes_pin_drift": pin_drift,
        "breaking_items": breaking_items[:5],
    }
    return items, stack_summary


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        host = parsed.netloc.lower().removeprefix("www.")
        path = parsed.path.rstrip("/")
        return f"{host}{path}"
    except Exception:
        return ""
