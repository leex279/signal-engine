"""GitHub Releases, Commits, and Markdown Changelog splitters."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from dateutil import parser as date_parser
import httpx

from signal_engine.models import SignalItem, make_changelog_id


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "signal-engine/0.1.0",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def extract_first_sentence(text: str) -> str:
    """Return the first real sentence or bullet from a changelog body, skipping boilerplate."""
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"^#+\s+", "", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"[`*_~]", "", line).strip()
        if not line:
            continue
        lower = line.lower()
        if any(
            skip in lower
            for skip in ("choose a tag", "subscribe", "full changelog", "what's changed")
        ):
            continue
        if len(line.split()) < 4:
            continue
        if len(line) > 140:
            return line[:137].rstrip() + "..."
        return line
    fallback = re.sub(r"\s+", " ", (text or "").strip())
    return fallback[:120] if fallback else "Release update"


def fetch_github_releases(
    source_name: str,
    owner_repo: str,
    label: str,
    per_page: int = 20,
) -> list[SignalItem]:
    """Fetch releases from GitHub Releases API (`per_page` capped at 20)."""
    url = f"https://api.github.com/repos/{owner_repo}/releases"
    items: list[SignalItem] = []
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        resp = client.get(url, params={"per_page": per_page}, headers=_github_headers())
        resp.raise_for_status()
        releases = resp.json()

    for rel in releases:
        if rel.get("draft"):
            continue
        rel_id = rel.get("id") or rel.get("tag_name")
        tag = rel.get("tag_name") or rel.get("name") or "release"
        body = (rel.get("body") or "").strip()
        html_url = rel.get("html_url") or f"https://github.com/{owner_repo}/releases"
        pub_str = rel.get("published_at") or rel.get("created_at")
        pub_dt = None
        if pub_str:
            try:
                pub_dt = date_parser.isoparse(pub_str).astimezone(timezone.utc)
            except Exception:
                pub_dt = None

        first_line = extract_first_sentence(body)
        title = f"{label} {tag}: {first_line}"
        items.append(
            SignalItem(
                id=f"gh-release:{owner_repo}:{rel_id}",
                source=source_name,
                title=title,
                url=html_url,
                body=body[:4000],
                published_at=pub_dt,
                engagement=None,
                metadata={
                    "repo": owner_repo,
                    "tag": tag,
                    "prerelease": bool(rel.get("prerelease")),
                },
            )
        )
    return items


def split_markdown_changelog(
    source_name: str,
    page_url: str,
    human_url: str,
    label: str,
    markdown_text: str,
    max_entries: int = 20,
) -> list[SignalItem]:
    """Split a Markdown changelog by versioned or dated headings into stable-ID SignalItems."""
    heading_re = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
    matches = list(heading_re.finditer(markdown_text))
    items: list[SignalItem] = []

    date_or_ver_re = re.compile(
        r"(v?\d+\.\d+(?:\.\d+)?|\b202\d-\d{2}-\d{2}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,?\s+202\d)?)",
        re.IGNORECASE,
    )

    for idx, match in enumerate(matches):
        heading = match.group(2).strip()
        if not date_or_ver_re.search(heading):
            continue
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown_text)
        body = markdown_text[start:end].strip()
        if not body:
            continue

        pub_dt = _parse_date_from_heading(heading)
        first_sentence = extract_first_sentence(body)
        title = f"{label} [{heading}]: {first_sentence}"
        item_id = make_changelog_id(page_url, heading, body)

        items.append(
            SignalItem(
                id=item_id,
                source=source_name,
                title=title,
                url=human_url,
                body=body[:4000],
                published_at=pub_dt,
                engagement=None,
                metadata={"heading": heading, "changelog_url": page_url},
            )
        )
        if len(items) >= max_entries:
            break

    return items


def _parse_date_from_heading(heading: str) -> datetime | None:
    """Extract a date from a heading if present; otherwise return None."""
    iso_m = re.search(r"\b(202\d-\d{2}-\d{2})\b", heading)
    if iso_m:
        try:
            return date_parser.isoparse(iso_m.group(1)).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    month_m = re.search(
        r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,?\s+202\d)?)\b",
        heading,
        re.IGNORECASE,
    )
    if month_m:
        try:
            now = datetime.now(timezone.utc)
            dt = date_parser.parse(month_m.group(1), default=now.replace(day=1))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt > now:
                dt = dt.replace(year=dt.year - 1)
            return dt
        except Exception:
            pass
    return None


def fetch_claude_code() -> list[SignalItem]:
    """Stage 1 source: Anthropic Claude Code releases + raw CHANGELOG.md."""
    items: list[SignalItem] = []
    try:
        items.extend(
            fetch_github_releases(
                source_name="claude-code",
                owner_repo="anthropics/claude-code",
                label="Claude Code",
                per_page=15,
            )
        )
    except Exception:
        pass

    changelog_raw_url = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
    human_url = "https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md"
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(changelog_raw_url, headers={"User-Agent": "signal-engine/0.1.0"})
            if resp.status_code == 200 and resp.text:
                entries = split_markdown_changelog(
                    source_name="claude-code",
                    page_url=changelog_raw_url,
                    human_url=human_url,
                    label="Claude Code Changelog",
                    markdown_text=resp.text,
                    max_entries=15,
                )
                # If CHANGELOG.md entries don't carry dates in headings, assign recent commit timestamp to latest entries
                if entries and all(e.published_at is None for e in entries):
                    now = datetime.now(timezone.utc)
                    for i, entry in enumerate(entries):
                        if i < 3:
                            entry.published_at = now
                items.extend(entries)
    except Exception:
        pass

    # Deduplicate in-memory by id
    seen: set[str] = set()
    deduped: list[SignalItem] = []
    for it in items:
        if it.id not in seen:
            seen.add(it.id)
            deduped.append(it)
    return deduped
