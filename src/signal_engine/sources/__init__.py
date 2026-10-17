"""Registry of all Signal Engine sources defined in PROFILE.md."""

from __future__ import annotations

from typing import Callable
from signal_engine.models import SignalItem
from signal_engine.sources.github_and_changelogs import (
    fetch_antigravity_cursor_browseros,
    fetch_claude_code,
    fetch_coleam00_skills,
    fetch_gemini_cli,
    fetch_github_viral_repos,
    fetch_hyperframes,
    fetch_ollama,
    fetch_openai_codex,
    fetch_video_toolchain,
)
from signal_engine.sources.communities_and_feeds import (
    fetch_hacker_news,
    fetch_model_radar,
    fetch_official_blogs,
    fetch_reddit,
    fetch_youtube_creators,
)

ALL_SOURCES: list[tuple[str, str, Callable[[], list[SignalItem]]]] = [
    ("claude-code", "Releases + Status RSS + Docs + llms.txt diff", fetch_claude_code),
    ("antigravity-cursor-browseros", "Antigravity + Cursor RSS + BrowserOS Releases", fetch_antigravity_cursor_browseros),
    ("gemini-cli", "Gemini CLI + python-genai + Gemini API Changelog", fetch_gemini_cli),
    ("hyperframes", "Releases + Commits + llms.txt diff", fetch_hyperframes),
    ("openai-codex", "Codex CLI + OpenAI Agents SDK Releases", fetch_openai_codex),
    ("coleam00-skills", "MCP + Skills + Agent SDK + Archon + caveman + gstack", fetch_coleam00_skills),
    ("video-toolchain", "ElevenLabs + GSAP + n8n + yt-dlp + ast-grep + graphify", fetch_video_toolchain),
    ("ollama", "Ollama + llama.cpp/whisper.cpp (ROCm/Vulkan/Models)", fetch_ollama),
    ("github-viral-repos", "GitHub Search API (viral new agent/MCP/LLM repos)", fetch_github_viral_repos),
    ("model-radar", "OpenRouter Models diff + HuggingFace Trending API", fetch_model_radar),
    ("official-blogs", "Anthropic Eng + Claude + OpenAI Dev + Willison + YT Blog", fetch_official_blogs),
    ("hacker-news", "HN Algolia API (9 AI/agent/tool queries)", fetch_hacker_news),
    ("reddit", "10 Subreddits top-of-day RSS with spacing", fetch_reddit),
    ("youtube-creators", "13 YouTube channels (Competitors, Creators, 1st-Party)", fetch_youtube_creators),
]
