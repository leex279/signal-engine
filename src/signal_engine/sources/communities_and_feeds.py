"""Community, Model Radar, Engineering Blogs, Hacker News, Reddit, and YouTube Creator feeds."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
import feedparser
import httpx

from signal_engine.models import SignalItem

SNAPSHOT_DIR = Path("data/snapshots")


def _strip_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        dt = date_parser.parse(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def fetch_official_blogs() -> list[SignalItem]:
    """Fetch high-signal engineering feeds (Anthropic Eng, Claude, OpenAI Dev, Simon Willison, YouTube Blog)."""
    feeds = [
        (
            "Anthropic Engineering",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml",
        ),
        (
            "Claude Blog",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_claude.xml",
        ),
        (
            "OpenAI Developer Changelog",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_openai_developer.xml",
        ),
        (
            "Anthropic News",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
        ),
        (
            "Ollama Blog",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_ollama.xml",
        ),
        ("Simon Willison", "https://simonwillison.net/atom/everything/"),
        ("YouTube Official Blog", "https://blog.youtube/rss/"),
    ]
    items: list[SignalItem] = []
    headers = {"User-Agent": "signal-engine/0.2.0"}

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for label, feed_url in feeds:
            try:
                resp = client.get(feed_url, headers=headers)
                if resp.status_code != 200:
                    continue
                parsed = feedparser.parse(resp.text)
                for entry in parsed.entries[:12]:
                    link = (entry.get("link") or "").strip()
                    title = (entry.get("title") or "").strip()
                    if not link or not title:
                        continue
                    summary = _strip_html(
                        entry.get("summary") or entry.get("description") or ""
                    )
                    pub_str = (
                        entry.get("published")
                        or entry.get("updated")
                        or entry.get("pubDate")
                    )
                    pub_dt = _parse_dt(pub_str)
                    uid = hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]
                    items.append(
                        SignalItem(
                            id=f"blog:{uid}",
                            source="official-blogs",
                            title=f"[{label}] {title}",
                            url=link,
                            body=summary[:3000],
                            published_at=pub_dt,
                            engagement=None,
                            metadata={"blog": label, "feed_url": feed_url, "repo": label},
                        )
                    )
            except Exception:
                continue
    return items


def fetch_model_radar() -> list[SignalItem]:
    """Fetch new models from OpenRouter API (daily diff + recent) and HuggingFace Trending Models."""
    items: list[SignalItem] = []
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    or_snap_path = SNAPSHOT_DIR / "openrouter_models.json"

    # 1. OpenRouter Models API
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get("https://openrouter.ai/api/v1/models")
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                prev_ids: set[str] = set()
                if or_snap_path.exists():
                    try:
                        prev_ids = set(json.loads(or_snap_path.read_text(encoding="utf-8")))
                    except Exception:
                        prev_ids = set()

                all_ids = [m.get("id") for m in models if m.get("id")]
                or_snap_path.write_text(json.dumps(all_ids, indent=2), encoding="utf-8")

                # Sort models by created timestamp descending
                models_sorted = sorted(
                    models, key=lambda m: int(m.get("created") or 0), reverse=True
                )
                candidates = (
                    [m for m in models_sorted if m.get("id") not in prev_ids]
                    if prev_ids
                    else models_sorted[:10]
                )
                for m in candidates[:12]:
                    mid = m.get("id") or ""
                    name = m.get("name") or mid
                    desc = (m.get("description") or "").strip()
                    created_ts = m.get("created")
                    pub_dt = (
                        datetime.fromtimestamp(float(created_ts), tz=timezone.utc)
                        if created_ts
                        else datetime.now(timezone.utc)
                    )
                    ctx = m.get("context_length")
                    items.append(
                        SignalItem(
                            id=f"openrouter-model:{mid}",
                            source="model-radar",
                            title=f"[OpenRouter New Model] {name} (`{mid}`, ctx={ctx})",
                            url=f"https://openrouter.ai/{mid}",
                            body=f"Model ID: {mid}\nContext Length: {ctx}\nDescription: {desc[:2000]}",
                            published_at=pub_dt,
                            engagement=None,
                            metadata={"model_id": mid, "repo": "openrouter-models"},
                        )
                    )
    except Exception:
        pass

    # 2. HuggingFace Trending Models (Gemma, GLM, Kimi, Qwen, DeepSeek, Llama, etc.)
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(
                "https://huggingface.co/api/models",
                params={"sort": "trendingScore", "limit": 20},
            )
            if resp.status_code == 200:
                for m in resp.json():
                    mid = m.get("id") or m.get("modelId") or ""
                    if not mid:
                        continue
                    likes = float(m.get("likes") or 0)
                    downloads = int(m.get("downloads") or 0)
                    pipeline_tag = m.get("pipeline_tag") or "model"
                    created_at = _parse_dt(m.get("createdAt")) or datetime.now(timezone.utc)
                    items.append(
                        SignalItem(
                            id=f"hf-trending:{mid}",
                            source="model-radar",
                            title=f"[HF Trending ★{int(likes)}] {mid} ({pipeline_tag}, {downloads:,} downloads)",
                            url=f"https://huggingface.co/{mid}",
                            body=f"HuggingFace trending model: {mid}\nPipeline: {pipeline_tag}\nLikes: {int(likes)}, Downloads: {downloads:,}\nTags: {', '.join((m.get('tags') or [])[:12])}",
                            published_at=created_at,
                            engagement=likes,
                            metadata={"model_id": mid, "repo": "hf-trending"},
                        )
                    )
    except Exception:
        pass

    return items


def fetch_hacker_news() -> list[SignalItem]:
    """Fetch recent AI/agent/coding stories from Hacker News Algolia API."""
    url = "https://hn.algolia.com/api/v1/search_by_date"
    queries = [
        "Claude",
        "Gemini",
        "OpenAI",
        "LLM",
        "MCP",
        "agent",
        "Ollama",
        "ElevenLabs",
        "Cursor",
    ]
    seen: set[str] = set()
    items: list[SignalItem] = []

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for q in queries:
            try:
                resp = client.get(
                    url,
                    params={
                        "query": q,
                        "tags": "story",
                        "numericFilters": "points>=5",
                        "hitsPerPage": 12,
                    },
                )
                resp.raise_for_status()
                hits = resp.json().get("hits", [])
                for hit in hits:
                    obj_id = str(hit.get("objectID") or "").strip()
                    if not obj_id or obj_id in seen:
                        continue
                    seen.add(obj_id)
                    title = (hit.get("title") or "").strip()
                    if not title:
                        continue
                    story_url = (
                        hit.get("url")
                        or f"https://news.ycombinator.com/item?id={obj_id}"
                    )
                    story_text = _strip_html(hit.get("story_text") or "")
                    points = float(hit.get("points") or 0)
                    comments = int(hit.get("num_comments") or 0)
                    pub_dt = _parse_dt(hit.get("created_at"))
                    body = (
                        f"{story_text}\nHN Discussion: https://news.ycombinator.com/item?id={obj_id} "
                        f"({int(points)} pts, {comments} comments)"
                    ).strip()
                    items.append(
                        SignalItem(
                            id=f"hn:{obj_id}",
                            source="hacker-news",
                            title=title,
                            url=story_url,
                            body=body[:3000],
                            published_at=pub_dt,
                            engagement=points,
                            metadata={
                                "hn_id": obj_id,
                                "num_comments": comments,
                                "author": hit.get("author"),
                                "repo": "hacker-news",
                            },
                        )
                    )
            except Exception:
                continue
    return items


def fetch_reddit() -> list[SignalItem]:
    """Fetch top-of-day posts across 10 targeted subreddits with rate-limit spacing and per-sub percentile."""
    subreddits = [
        "ClaudeAI",
        "ClaudeCode",
        "LocalLLaMA",
        "ChatGPTCoding",
        "mcp",
        "google_antigravity",
        "cursor",
        "GeminiAI",
        "elevenlabs",
        "ollama",
    ]
    items: list[SignalItem] = []

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for idx, sub in enumerate(subreddits):
            if idx > 0:
                time.sleep(2.2)
            headers = {
                "User-Agent": f"windows:signal-engine.v2.{idx}:0.2.0 (by /u/signal_engine_local)",
                "Accept": "application/atom+xml, text/xml, application/json",
            }
            sub_items: list[SignalItem] = []

            # Try RSS first (more reliable without OAuth on Reddit, returns top of day in order)
            rss_url = f"https://www.reddit.com/r/{sub}/top/.rss?t=day&limit=12"
            try:
                resp = client.get(rss_url, headers=headers)
                if resp.status_code == 429:
                    time.sleep(3.5)
                    resp = client.get(rss_url, headers=headers)
                if resp.status_code == 200 and resp.text:
                    parsed = feedparser.parse(resp.text)
                    total_entries = max(len(parsed.entries), 1)
                    for rank_idx, entry in enumerate(parsed.entries[:12]):
                        entry_id = entry.get("id") or entry.get("link") or ""
                        title = (entry.get("title") or "").strip()
                        link = (entry.get("link") or "").strip()
                        if not entry_id or not title:
                            continue
                        short_id = entry_id.split("/")[-1] if "/" in entry_id else entry_id
                        body = _strip_html(entry.get("summary") or "")
                        pub_dt = _parse_dt(entry.get("updated") or entry.get("published"))
                        # Top RSS entries are already ranked by daily score; assign synthetic rank score (top 60% >= 15)
                        percentile = 1.0 - (rank_idx / total_entries)
                        synthetic_score = round(10.0 + 40.0 * percentile, 1)
                        sub_items.append(
                            SignalItem(
                                id=f"reddit:{sub}:{short_id}",
                                source="reddit",
                                title=f"[r/{sub}] {title}",
                                url=link,
                                body=body[:3000],
                                published_at=pub_dt,
                                engagement=synthetic_score,
                                metadata={
                                    "subreddit": sub,
                                    "rank_in_sub": rank_idx + 1,
                                    "sub_percentile": round(percentile, 2),
                                    "repo": f"r/{sub}",
                                },
                            )
                        )
            except Exception:
                pass

            items.extend(sub_items)
    return items


def fetch_youtube_creators() -> list[SignalItem]:
    """Fetch recent uploads from creator, competitor, first-party, and YouTube-policy channels."""
    # (name, channel_id, is_competitor)
    channels = [
        ("Cloud Codes", "UC0DZj1PNa_Fp0MU6uPSKv5w", True),
        ("The Stack ai", "UCjete_rlEo4zKvkzJNCMzsA", True),
        ("InsiderForce", "UC8L6EV01fAJ2A0sDpsQ-T5g", True),
        ("Cole Medin", "UCMwVTLZIRRUyyVrkjDpn4pA", False),
        ("Simon Scrapes", "UCdCR4-uYOg5ju-IUuDnfnQA", False),
        ("IndyDevDan", "UC_x36zCEGilGpB1m-V4gmjg", False),
        ("AI Explained", "UCNJ1Ymd5yFuUPtn21xtRbbw", False),
        ("Anthropic", "UCrDwWp7EBBv4NwvScIpBDOA", False),
        ("Google DeepMind", "UCP7jMXSY2xbc3KCAE0MHQ-A", False),
        ("Google for Developers", "UC_x5XG1OV2P6uZZ5FSM9Ttw", False),
        ("Creator Insider", "UCGg-UqjRgzhYDPJMr-9HXCg", False),
        ("vidIQ", "UCZLFu8bHbwtnIgWLg5UtINw", False),
        ("Sam Witteveen", "UCSdphiIAFdD_16nNOpliTIw", False),
        ("Developers Digest", "UCuE6iwZKgGz8s6kznBRI9LQ", False),
        ("Fireship", "UCsBjURrPoezykLs9EqgamOA", False),
    ]
    items: list[SignalItem] = []
    headers = {"User-Agent": "signal-engine/0.2.0"}

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for creator, channel_id, is_competitor in channels:
            feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            try:
                resp = None
                for attempt in range(3):
                    try:
                        resp = client.get(feed_url, headers=headers)
                        if resp.status_code == 200:
                            break
                    except httpx.HTTPError:
                        resp = None
                    time.sleep(1.5 * (attempt + 1))
                if resp is None or resp.status_code != 200:
                    print(f"[youtube-creators] {creator}: feed failed ({resp.status_code if resp is not None else 'no response'})")
                    continue
                parsed = feedparser.parse(resp.text)
                for entry in parsed.entries[:6]:
                    vid_id = entry.get("yt_videoid") or entry.get("id") or ""
                    title = (entry.get("title") or "").strip()
                    link = (entry.get("link") or "").strip()
                    if not vid_id or not title:
                        continue
                    summary = (entry.get("summary") or "").strip()
                    pub_dt = _parse_dt(entry.get("published") or entry.get("updated"))
                    views = None
                    media_stats = entry.get("media_statistics")
                    if isinstance(media_stats, dict) and media_stats.get("views"):
                        try:
                            views = float(media_stats["views"])
                        except Exception:
                            views = None
                    prefix = f"[YouTube Competitor - {creator}]" if is_competitor else f"[YouTube - {creator}]"
                    items.append(
                        SignalItem(
                            id=f"yt:{vid_id}",
                            source="youtube-creators",
                            title=f"{prefix} {title}",
                            url=link,
                            body=summary[:3000],
                            published_at=pub_dt,
                            engagement=views,
                            metadata={
                                "creator": creator,
                                "channel_id": channel_id,
                                "is_competitor": is_competitor,
                                "repo": f"yt:{creator}",
                            },
                        )
                    )
            except Exception:
                continue
    return items


CLAUDE_RELEASE_NOTES_URL = "https://support.claude.com/en/articles/12138966-release-notes"


def fetch_claude_apps() -> list[SignalItem]:
    """Claude app release notes (Claude desktop, Cowork, Chrome, plugins, plans/credits) from support.claude.com."""
    items: list[SignalItem] = []
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(CLAUDE_RELEASE_NOTES_URL, headers={"User-Agent": "signal-engine/0.3.0"})
            resp.raise_for_status()
    except Exception:
        return items

    soup = BeautifulSoup(resp.text, "html.parser")
    root = soup.find("article") or soup
    current: list | None = None
    entries: list[tuple[str, list[str]]] = []
    for el in root.find_all(["h2", "h3", "p", "li"]):
        if el.name == "h3":
            current = []
            entries.append((el.get_text(" ", strip=True), current))
        elif el.name == "h2":
            current = None
        elif current is not None and el.find_parent("li") is None:
            current.append(el.get_text(" ", strip=True))

    for date_text, paras in entries[:6]:
        pub_dt = _parse_dt(date_text)
        body = " ".join(paras).strip()
        if not body:
            continue
        # The first paragraph usually starts with the feature headline; use it as the title.
        title = paras[0][:110] if paras else date_text
        uid = hashlib.sha256(f"{date_text}|{body[:200]}".encode("utf-8")).hexdigest()[:16]
        items.append(
            SignalItem(
                id=f"claude-apps:{uid}",
                source="claude-apps",
                title=f"[Claude apps {date_text}] {title}",
                url=f"{CLAUDE_RELEASE_NOTES_URL}",
                body=body[:3000],
                published_at=pub_dt,
                metadata={"repo": "Claude apps"},
            )
        )
    return items


# Labs whose new open-weight / model repos are day-0 video material for the channel.
LAB_HF_ORGS = [
    "meta-llama",
    "facebook",
    "mistralai",
    "google",
    "Qwen",
    "deepseek-ai",
    "zai-org",
    "moonshotai",
    "openai",
    "nvidia",
    "microsoft",
]


def fetch_lab_models() -> list[SignalItem]:
    """Newest model repos from major labs on HuggingFace (Meta, Mistral, Google, Qwen, DeepSeek, Z.ai, Moonshot...)."""
    items: list[SignalItem] = []
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for org in LAB_HF_ORGS:
            try:
                resp = client.get(
                    "https://huggingface.co/api/models",
                    params={"author": org, "sort": "createdAt", "direction": "-1", "limit": 5},
                )
                if resp.status_code != 200:
                    continue
                for m in resp.json():
                    mid = m.get("id") or ""
                    created = _parse_dt(m.get("createdAt"))
                    if not mid or created is None:
                        continue
                    # Skip quantized/derivative repos: only primary releases.
                    low = mid.lower()
                    if any(x in low for x in ("-gguf", "-awq", "-gptq", "-fp8", "-int4", "-int8", "-mlx", "-bnb")):
                        continue
                    tags = ", ".join((m.get("tags") or [])[:8])
                    items.append(
                        SignalItem(
                            id=f"lab-model:{mid}",
                            source="lab-models",
                            title=f"[{org}] New model repo: {mid}",
                            url=f"https://huggingface.co/{mid}",
                            body=f"New HuggingFace repo {mid} from {org}. Pipeline: {m.get('pipeline_tag')}. Tags: {tags}.",
                            published_at=created,
                            engagement=float(m.get("likes") or 0),
                            metadata={"repo": f"HF {org}", "lab": org},
                        )
                    )
            except Exception:
                continue
    return items
