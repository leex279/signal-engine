"""GitHub Releases, Commits, Viral Repo Search, llms.txt Diffs, and Changelog Splitters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
import feedparser
import httpx

from signal_engine.models import SignalItem, make_changelog_id

SNAPSHOT_DIR = Path("data/snapshots")


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "signal-engine/0.2.0",
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
            for skip in (
                "choose a tag",
                "subscribe",
                "full changelog",
                "what's changed",
                "new contributors",
            )
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
    per_page: int = 10,
) -> list[SignalItem]:
    """Fetch releases from GitHub Releases API."""
    url = f"https://api.github.com/repos/{owner_repo}/releases"
    items: list[SignalItem] = []
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        resp = client.get(url, params={"per_page": per_page}, headers=_github_headers())
        if resp.status_code != 200:
            return []
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


def fetch_github_commits(
    source_name: str,
    owner_repo: str,
    label: str,
    per_page: int = 10,
) -> list[SignalItem]:
    """Fetch recent commits from GitHub Commits API for repos that ship via main branch."""
    url = f"https://api.github.com/repos/{owner_repo}/commits"
    items: list[SignalItem] = []
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        resp = client.get(url, params={"per_page": per_page}, headers=_github_headers())
        if resp.status_code != 200:
            return []
        commits = resp.json()

    for c in commits:
        sha = (c.get("sha") or "")[:12]
        commit_obj = c.get("commit") or {}
        message = (commit_obj.get("message") or "").strip()
        if not message:
            continue
        lines = message.splitlines()
        headline = lines[0].strip()
        if headline.lower().startswith("merge pull request") and len(lines) > 1:
            headline = next((ln.strip() for ln in lines[1:] if ln.strip()), headline)

        author_info = commit_obj.get("committer") or commit_obj.get("author") or {}
        pub_str = author_info.get("date")
        pub_dt = None
        if pub_str:
            try:
                pub_dt = date_parser.isoparse(pub_str).astimezone(timezone.utc)
            except Exception:
                pub_dt = None

        html_url = c.get("html_url") or f"https://github.com/{owner_repo}/commit/{sha}"
        items.append(
            SignalItem(
                id=f"gh-commit:{owner_repo}:{sha}",
                source=source_name,
                title=f"{label} ({sha[:7]}): {headline}",
                url=html_url,
                body=message[:4000],
                published_at=pub_dt,
                engagement=None,
                metadata={"repo": owner_repo, "sha": sha},
            )
        )
    return items


def split_markdown_changelog(
    source_name: str,
    page_url: str,
    human_url: str,
    label: str,
    markdown_text: str,
    max_entries: int = 15,
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
                metadata={"heading": heading, "changelog_url": page_url, "repo": label},
            )
        )
        if len(items) >= max_entries:
            break

    return items


def fetch_html_changelog_entries(
    source_name: str,
    url: str,
    label: str,
    max_entries: int = 10,
) -> list[SignalItem]:
    """Fetch an HTML or Markdown changelog page and split by dated/versioned headings."""
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "signal-engine/0.2.0"})
            if resp.status_code != 200 or not resp.text:
                return []
            if url.endswith(".md") or resp.text.lstrip().startswith("#"):
                md_text = resp.text
            else:
                soup = BeautifulSoup(resp.text, "html.parser")
                lines: list[str] = []
                for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
                    txt = el.get_text(" ", strip=True)
                    if not txt:
                        continue
                    if el.name in ("h1", "h2", "h3", "h4"):
                        lines.append(f"\n## {txt}\n")
                    else:
                        lines.append(f"- {txt}")
                md_text = "\n".join(lines)
            entries = split_markdown_changelog(
                source_name=source_name,
                page_url=url,
                human_url=url,
                label=label,
                markdown_text=md_text,
                max_entries=max_entries,
            )
            now = datetime.now(timezone.utc)
            for i, entry in enumerate(entries):
                if entry.published_at is None and i < 3:
                    entry.published_at = now
            return entries
    except Exception:
        return []


def diff_llms_txt_snapshot(
    source_name: str,
    url: str,
    snapshot_name: str,
    label: str,
) -> list[SignalItem]:
    """Diff an llms.txt index daily and emit a SignalItem when new docs/blocks appear."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snap_path = SNAPSHOT_DIR / f"{snapshot_name}.json"
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "signal-engine/0.2.0"})
            if resp.status_code != 200 or not resp.text:
                return []
            current_lines = [
                ln.strip()
                for ln in resp.text.splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
    except Exception:
        return []

    prev_lines: set[str] = set()
    if snap_path.exists():
        try:
            prev_lines = set(json.loads(snap_path.read_text(encoding="utf-8")))
        except Exception:
            prev_lines = set()

    snap_path.write_text(json.dumps(current_lines, indent=2, ensure_ascii=False), encoding="utf-8")

    if not prev_lines:
        return []

    added = [ln for ln in current_lines if ln not in prev_lines]
    if not added:
        return []

    now = datetime.now(timezone.utc)
    joined = "\n".join(added[:20])
    uid = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:14]
    return [
        SignalItem(
            id=f"llms-diff:{snapshot_name}:{uid}",
            source=source_name,
            title=f"{label} llms.txt diff: {len(added)} new docs/entries added ({added[0][:80]})",
            url=url,
            body=f"New lines in {url}:\n{joined}",
            published_at=now,
            engagement=None,
            metadata={"repo": label, "added_count": len(added)},
        )
    ]


def _parse_date_from_heading(heading: str) -> datetime | None:
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


def _dedupe(items: list[SignalItem]) -> list[SignalItem]:
    seen: set[str] = set()
    out: list[SignalItem] = []
    for it in items:
        if it.id not in seen:
            seen.add(it.id)
            out.append(it)
    return out


def fetch_claude_code() -> list[SignalItem]:
    """Anthropic Claude Code releases + raw CHANGELOG.md + docs release notes + status RSS + llms.txt diff."""
    items: list[SignalItem] = []
    items.extend(
        fetch_github_releases(
            source_name="claude-code",
            owner_repo="anthropics/claude-code",
            label="Claude Code",
            per_page=10,
        )
    )
    # Claude status incidents RSS (usage limit / outage tracking)
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(
                "https://status.claude.com/history.rss",
                headers={"User-Agent": "signal-engine/0.2.0"},
            )
            if resp.status_code == 200:
                parsed = feedparser.parse(resp.text)
                for entry in parsed.entries[:6]:
                    link = (entry.get("link") or "").strip()
                    title = (entry.get("title") or "").strip()
                    if not link or not title:
                        continue
                    pub_dt = None
                    if entry.get("published"):
                        try:
                            pub_dt = date_parser.parse(entry.get("published")).astimezone(timezone.utc)
                        except Exception:
                            pub_dt = None
                    uid = hashlib.sha256(f"{link}|{title}".encode("utf-8")).hexdigest()[:14]
                    summary = BeautifulSoup(entry.get("summary") or "", "html.parser").get_text(" ", strip=True)
                    items.append(
                        SignalItem(
                            id=f"claude-status:{uid}",
                            source="claude-code",
                            title=f"[Claude Status] {title}",
                            url=link,
                            body=summary[:2000],
                            published_at=pub_dt,
                            engagement=None,
                            metadata={"repo": "claude-status"},
                        )
                    )
    except Exception:
        pass

    items.extend(
        fetch_html_changelog_entries(
            source_name="claude-code",
            url="https://docs.claude.com/en/release-notes/overview",
            label="Claude API Release Notes",
            max_entries=6,
        )
    )
    items.extend(
        diff_llms_txt_snapshot(
            source_name="claude-code",
            url="https://code.claude.com/docs/llms.txt",
            snapshot_name="claude_code_llms_txt",
            label="Claude Code Docs",
        )
    )
    return _dedupe(items)


def fetch_antigravity_cursor_browseros() -> list[SignalItem]:
    """Antigravity changelog, Cursor changelog RSS, and BrowserOS releases."""
    items: list[SignalItem] = []
    items.extend(
        fetch_html_changelog_entries(
            source_name="antigravity-cursor-browseros",
            url="https://antigravity.google/changelog",
            label="Google Antigravity",
            max_entries=8,
        )
    )
    items.extend(
        fetch_github_releases(
            source_name="antigravity-cursor-browseros",
            owner_repo="browseros-ai/BrowserOS",
            label="BrowserOS",
            per_page=8,
        )
    )
    # Cursor changelog RSS from Olshansk/rss-feeds
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(
                "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_cursor.xml",
                headers={"User-Agent": "signal-engine/0.2.0"},
            )
            if resp.status_code == 200:
                parsed = feedparser.parse(resp.text)
                for entry in parsed.entries[:8]:
                    link = (entry.get("link") or "").strip()
                    title = (entry.get("title") or "").strip()
                    if not link or not title:
                        continue
                    pub_dt = None
                    if entry.get("published") or entry.get("updated"):
                        try:
                            pub_dt = date_parser.parse(
                                entry.get("published") or entry.get("updated")
                            ).astimezone(timezone.utc)
                        except Exception:
                            pub_dt = None
                    summary = BeautifulSoup(
                        entry.get("summary") or entry.get("description") or "",
                        "html.parser",
                    ).get_text(" ", strip=True)
                    uid = hashlib.sha256(f"{link}|{title}".encode("utf-8")).hexdigest()[:14]
                    items.append(
                        SignalItem(
                            id=f"cursor:{uid}",
                            source="antigravity-cursor-browseros",
                            title=f"[Cursor Changelog] {title}",
                            url=link,
                            body=summary[:3000],
                            published_at=pub_dt,
                            engagement=None,
                            metadata={"repo": "cursor"},
                        )
                    )
    except Exception:
        pass
    return _dedupe(items)


def fetch_gemini_cli() -> list[SignalItem]:
    """Google Gemini CLI + python-genai SDK + Gemini API changelog."""
    items: list[SignalItem] = []
    items.extend(
        fetch_github_releases(
            source_name="gemini-cli",
            owner_repo="google-gemini/gemini-cli",
            label="Gemini CLI",
            per_page=10,
        )
    )
    items.extend(
        fetch_github_releases(
            source_name="gemini-cli",
            owner_repo="googleapis/python-genai",
            label="google-genai SDK",
            per_page=6,
        )
    )
    items.extend(
        fetch_html_changelog_entries(
            source_name="gemini-cli",
            url="https://ai.google.dev/gemini-api/docs/changelog",
            label="Gemini API Changelog",
            max_entries=6,
        )
    )
    return _dedupe(items)


def fetch_hyperframes() -> list[SignalItem]:
    """HeyGen HyperFrames releases, commits, Mintlify changelog, and llms.txt diff."""
    items: list[SignalItem] = []
    items.extend(
        fetch_github_releases(
            source_name="hyperframes",
            owner_repo="heygen-com/hyperframes",
            label="HyperFrames",
            per_page=8,
        )
    )
    items.extend(
        fetch_github_commits(
            source_name="hyperframes",
            owner_repo="heygen-com/hyperframes",
            label="HyperFrames",
            per_page=10,
        )
    )
    items.extend(
        diff_llms_txt_snapshot(
            source_name="hyperframes",
            url="https://hyperframes.heygen.com/llms.txt",
            snapshot_name="hyperframes_llms_txt",
            label="HyperFrames",
        )
    )
    return _dedupe(items)


def fetch_openai_codex() -> list[SignalItem]:
    """OpenAI Codex CLI + openai-agents-python SDK releases."""
    items: list[SignalItem] = []
    items.extend(
        fetch_github_releases(
            source_name="openai-codex",
            owner_repo="openai/codex",
            label="OpenAI Codex",
            per_page=8,
        )
    )
    items.extend(
        fetch_github_releases(
            source_name="openai-codex",
            owner_repo="openai/openai-agents-python",
            label="OpenAI Agents SDK",
            per_page=6,
        )
    )
    return _dedupe(items)


def fetch_coleam00_skills() -> list[SignalItem]:
    """MCP, Skills, Agent SDKs, Caveman, gstack, and Archon."""
    items: list[SignalItem] = []
    for repo, label in (
        ("modelcontextprotocol/modelcontextprotocol", "MCP Spec"),
        ("anthropics/claude-agent-sdk-python", "Claude Agent SDK"),
        ("coleam00/Archon", "Cole Medin Archon"),
    ):
        items.extend(
            fetch_github_releases(
                source_name="coleam00-skills",
                owner_repo=repo,
                label=label,
                per_page=5,
            )
        )
    for repo, label in (
        ("coleam00/skills", "coleam00/skills"),
        ("anthropics/skills", "anthropics/skills"),
        ("JuliusBrussee/caveman", "caveman"),
        ("garrytan/gstack", "gstack"),
    ):
        items.extend(
            fetch_github_commits(
                source_name="coleam00-skills",
                owner_repo=repo,
                label=label,
                per_page=5,
            )
        )
    return _dedupe(items)


def fetch_video_toolchain() -> list[SignalItem]:
    """Production video toolchain: ElevenLabs, GSAP, n8n, yt-dlp, ast-grep, graphify."""
    items: list[SignalItem] = []
    for repo, label in (
        ("elevenlabs/elevenlabs-python", "ElevenLabs Python SDK"),
        ("greensock/GSAP", "GSAP"),
        ("n8n-io/n8n", "n8n"),
        ("yt-dlp/yt-dlp", "yt-dlp"),
        ("ast-grep/ast-grep", "ast-grep"),
    ):
        items.extend(
            fetch_github_releases(
                source_name="video-toolchain",
                owner_repo=repo,
                label=label,
                per_page=5,
            )
        )
    for repo, label in (
        ("elevenlabs/skills", "elevenlabs/skills"),
        ("greensock/gsap-skills", "greensock/gsap-skills"),
        ("safishamsi/graphify", "graphify"),
    ):
        items.extend(
            fetch_github_commits(
                source_name="video-toolchain",
                owner_repo=repo,
                label=label,
                per_page=5,
            )
        )
    items.extend(
        fetch_html_changelog_entries(
            source_name="video-toolchain",
            url="https://elevenlabs.io/docs/changelog",
            label="ElevenLabs Changelog",
            max_entries=5,
        )
    )
    return _dedupe(items)


def fetch_ollama() -> list[SignalItem]:
    """Ollama + llama.cpp / whisper.cpp (filtered to new models, Vulkan, or ROCm for 7900 XTX)."""
    items: list[SignalItem] = []
    items.extend(
        fetch_github_releases(
            source_name="ollama",
            owner_repo="ollama/ollama",
            label="Ollama",
            per_page=10,
        )
    )
    gpu_model_re = re.compile(
        r"\b(rocm|vulkan|hip|radeon|gemma|qwen|glm|kimi|deepseek|nemotron|llama|mistral|gguf|quant)\b",
        re.IGNORECASE,
    )
    for repo, label in (
        ("ggml-org/llama.cpp", "llama.cpp"),
        ("ggml-org/whisper.cpp", "whisper.cpp"),
    ):
        rels = fetch_github_releases(
            source_name="ollama",
            owner_repo=repo,
            label=label,
            per_page=10,
        )
        for r in rels:
            if gpu_model_re.search(f"{r.title} {r.body}"):
                items.append(r)
    return _dedupe(items)


def fetch_github_viral_repos() -> list[SignalItem]:
    """GitHub Search API for newly created viral repos in claude-code / mcp / agent-skills."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    queries = [
        f"created:>{cutoff} stars:>150 (claude-code OR mcp OR \"claude skills\" OR \"coding agent\")",
        f"created:>{cutoff} stars:>250 (llm OR agent ORtts OR video) language:Python",
    ]
    items: list[SignalItem] = []
    url = "https://api.github.com/search/repositories"
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for q in queries:
            try:
                resp = client.get(
                    url,
                    params={"q": q, "sort": "stars", "order": "desc", "per_page": 10},
                    headers=_github_headers(),
                )
                if resp.status_code != 200:
                    continue
                for repo in resp.json().get("items", []):
                    full_name = repo.get("full_name") or ""
                    if not full_name:
                        continue
                    desc = (repo.get("description") or "").strip()
                    stars = float(repo.get("stargazers_count") or 0)
                    html_url = repo.get("html_url") or f"https://github.com/{full_name}"
                    pub_dt = None
                    if repo.get("created_at"):
                        try:
                            pub_dt = date_parser.isoparse(repo["created_at"]).astimezone(timezone.utc)
                        except Exception:
                            pub_dt = None
                    topics = ", ".join(repo.get("topics") or [])
                    items.append(
                        SignalItem(
                            id=f"gh-viral:{full_name}",
                            source="github-viral-repos",
                            title=f"[Viral Repo ★{int(stars)}] {full_name}: {desc[:120]}",
                            url=html_url,
                            body=f"Repository: {full_name} ({int(stars)} stars)\nDescription: {desc}\nTopics: {topics}",
                            published_at=pub_dt,
                            engagement=stars,
                            metadata={"repo": full_name, "stars": stars, "topics": repo.get("topics") or []},
                        )
                    )
            except Exception:
                continue
    return _dedupe(items)
