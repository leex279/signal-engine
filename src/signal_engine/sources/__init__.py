"""Registry of all Signal Engine sources defined in PROFILE.md."""

from __future__ import annotations

from typing import Callable
from signal_engine.models import SignalItem
from signal_engine.sources.github_and_changelogs import (
    fetch_claude_code,
    fetch_coleam00_skills,
    fetch_gemini_cli,
    fetch_hyperframes,
    fetch_ollama,
    fetch_openai_codex,
)
from signal_engine.sources.communities_and_feeds import (
    fetch_hacker_news,
    fetch_official_blogs,
    fetch_reddit,
    fetch_youtube_creators,
)

ALL_SOURCES: list[tuple[str, str, Callable[[], list[SignalItem]]]] = [
    ("claude-code", "GitHub Releases API + raw CHANGELOG.md", fetch_claude_code),
    ("gemini-cli", "GitHub Releases API (google-gemini/gemini-cli)", fetch_gemini_cli),
    ("hyperframes", "GitHub Releases/Commits + Mintlify Changelog", fetch_hyperframes),
    ("openai-codex", "GitHub Releases API (openai/codex)", fetch_openai_codex),
    ("coleam00-skills", "GitHub Commits API (coleam00/skills)", fetch_coleam00_skills),
    ("ollama", "GitHub Releases API (ollama/ollama)", fetch_ollama),
    ("official-blogs", "RSS/Atom feeds (OpenAI, Google AI, Anthropic)", fetch_official_blogs),
    ("hacker-news", "HN Algolia API (stories)", fetch_hacker_news),
    ("reddit", "Subreddit top-of-day JSON/RSS (4 subs)", fetch_reddit),
    ("youtube-creators", "YouTube channel RSS feeds (3 creators)", fetch_youtube_creators),
]
