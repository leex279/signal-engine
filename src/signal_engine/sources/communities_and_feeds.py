"""Community and feed sources: Official Blogs, Hacker News, Reddit, YouTube Creators."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
import time
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
import feedparser
import httpx

from signal_engine.models import SignalItem


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
    """Fetch official AI blogs & release feeds (OpenAI, Google AI, Anthropic)."""
    feeds = [
        ("OpenAI News", "https://openai.com/news/rss.xml"),
        ("Google AI Blog", "https://blog.google/technology/ai/rss/"),
        (
            "Anthropic Research & News",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
        ),
    ]
    items: list[SignalItem] = []
    headers = {"User-Agent": "signal-engine/0.1.0"}

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for label, feed_url in feeds:
            try:
                resp = client.get(feed_url, headers=headers)
                if resp.status_code != 200:
                    continue
                parsed = feedparser.parse(resp.text)
                for entry in parsed.entries[:15]:
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
                            metadata={"blog": label, "feed_url": feed_url},
                        )
                    )
            except Exception:
                continue
    return items


def fetch_hacker_news() -> list[SignalItem]:
    """Fetch recent AI/agent/coding stories from Hacker News Algolia API."""
    url = "https://hn.algolia.com/api/v1/search_by_date"
    queries = ["Claude", "Gemini", "OpenAI", "LLM", "MCP", "agent", "Ollama"]
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
                        "hitsPerPage": 15,
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
                            },
                        )
                    )
            except Exception:
                continue
    return items


def fetch_reddit() -> list[SignalItem]:
    """Fetch top-of-day posts from r/ClaudeAI, r/LocalLLaMA, r/singularity, r/ChatGPTCoding."""
    subreddits = ["ClaudeAI", "LocalLLaMA", "singularity", "ChatGPTCoding"]
    items: list[SignalItem] = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) signal-engine/0.1.0",
        "Accept": "application/json, application/atom+xml, text/xml",
    }

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for sub in subreddits:
            json_url = f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=15"
            fetched_sub = False
            try:
                resp = client.get(json_url, headers=headers)
                if resp.status_code == 200:
                    children = (resp.json().get("data") or {}).get("children") or []
                    for child in children:
                        data = child.get("data") or {}
                        post_id = data.get("id")
                        title = (data.get("title") or "").strip()
                        if not post_id or not title:
                            continue
                        permalink = data.get("permalink") or f"/r/{sub}/comments/{post_id}/"
                        url = f"https://www.reddit.com{permalink}"
                        selftext = (data.get("selftext") or "").strip()
                        ext_url = data.get("url") or ""
                        body = selftext
                        if ext_url and ext_url != url:
                            body = f"External link: {ext_url}\n\n{selftext}".strip()
                        created_utc = data.get("created_utc")
                        pub_dt = (
                            datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
                            if created_utc
                            else None
                        )
                        score = float(data.get("score") or data.get("ups") or 0)
                        items.append(
                            SignalItem(
                                id=f"reddit:t3_{post_id}",
                                source="reddit",
                                title=f"[r/{sub}] {title}",
                                url=url,
                                body=body[:3000],
                                published_at=pub_dt,
                                engagement=score,
                                metadata={
                                    "subreddit": sub,
                                    "num_comments": data.get("num_comments", 0),
                                    "flair": data.get("link_flair_text"),
                                },
                            )
                        )
                    if children:
                        fetched_sub = True
            except Exception:
                pass

            if not fetched_sub:
                rss_url = f"https://www.reddit.com/r/{sub}/top/.rss?t=day&limit=15"
                try:
                    resp = client.get(rss_url, headers=headers)
                    if resp.status_code == 200:
                        parsed = feedparser.parse(resp.text)
                        for entry in parsed.entries[:15]:
                            entry_id = entry.get("id") or entry.get("link") or ""
                            title = (entry.get("title") or "").strip()
                            link = (entry.get("link") or "").strip()
                            if not entry_id or not title:
                                continue
                            short_id = entry_id.split("/")[-1] if "/" in entry_id else entry_id
                            body = _strip_html(entry.get("summary") or "")
                            pub_dt = _parse_dt(entry.get("updated") or entry.get("published"))
                            items.append(
                                SignalItem(
                                    id=f"reddit:{short_id}",
                                    source="reddit",
                                    title=f"[r/{sub}] {title}",
                                    url=link,
                                    body=body[:3000],
                                    published_at=pub_dt,
                                    engagement=20.0,
                                    metadata={"subreddit": sub},
                                )
                            )
                except Exception:
                    pass
            time.sleep(0.2)
    return items


def fetch_youtube_creators() -> list[SignalItem]:
    """Fetch recent uploads from Cole Medin, IndyDevDan, and AI Explained via YouTube RSS."""
    channels = [
        ("Cole Medin", "UCMwVTLZIRRUyyVrkjDpn4pA"),
        ("IndyDevDan", "UC_x36zCEGilGpB1m-V4gmjg"),
        ("AI Explained", "UCNJ1Ymd5yFuUPtn21xtRbbw"),
    ]
    items: list[SignalItem] = []
    headers = {"User-Agent": "signal-engine/0.1.0"}

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for creator, channel_id in channels:
            feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            try:
                resp = client.get(feed_url, headers=headers)
                if resp.status_code != 200:
                    continue
                parsed = feedparser.parse(resp.text)
                for entry in parsed.entries[:10]:
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
                    items.append(
                        SignalItem(
                            id=f"yt:{vid_id}",
                            source="youtube-creators",
                            title=f"[YouTube - {creator}] {title}",
                            url=link,
                            body=summary[:3000],
                            published_at=pub_dt,
                            engagement=views,
                            metadata={"creator": creator, "channel_id": channel_id},
                        )
                    )
            except Exception:
                continue
    return items
