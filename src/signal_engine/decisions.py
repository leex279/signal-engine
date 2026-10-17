"""Stage 4: The Decision Pass (TypeSafe Jev via OpenRouter with 3 questions including video_candidate)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any
from urllib.parse import urlparse
import httpx

from signal_engine.models import SignalItem

RELEVANCE_INSTRUCTIONS = (
    "How relevant is this item to an AI engineer and YouTube creator (DIY Smart Code) who builds with "
    "coding agents, skills, workflows, browser automation, TTS/audio, and programmatic video "
    "(specifically Google Antigravity, Gemini CLI/API/Gemma, Anthropic Claude Code/API, HeyGen HyperFrames, "
    "OpenAI Codex, Cursor, BrowserOS, MCP servers, ElevenLabs, GSAP, n8n, and local LLMs on Ollama/llama.cpp/ROCm)? "
    "Note: an unfamiliar new product, repo, or model name is NOT a reason to score lower "
    "if it solves one of these problems."
)

RELEVANCE_CRITERIA = [
    "Level 0: Unrelated to AI engineering, coding agents, LLMs, browser automation, TTS, or programmatic video; or general reaction/praise/complaint threads and end-user game/art showcases with no reusable developer tool or workflow.",
    "Level 1: General AI news, funding/valuation drama, policy debates, subjective complaints ('X feels the same'), or vague praise ('Mind blown by X') that does not change how a builder works.",
    "Level 2: Adjacent developer topic, beginner tutorial, or minor internal refactor without actionable impact on my stack or videos.",
    "Level 3: Concrete agent workflow, harness integration (e.g. integrating Jev into Claude Code), benchmark tool (e.g. Llmspeed), skill, MCP server, or open-weight model release (Gemma, Qwen, GLM, Kimi, DeepSeek) a builder can adopt.",
    "Level 4: Direct release, changelog update, new flag/env-var, skill, outage/limit change, or breaking change in core tools (Antigravity, Gemini CLI/API, Claude Code/API, HyperFrames, OpenAI Codex, Cursor, BrowserOS, MCP, ElevenLabs, GSAP, Ollama/llama.cpp).",
]

NEW_INSTRUCTIONS = (
    "Does this item report something new, technical, and concrete for an AI developer (a release, "
    "changelog update, feature, open-source tool/repo/skill, measured benchmark, outage/limit change, or reproducible agent engineering workflow)?"
)

NEW_CRITERIA = {
    "true": (
        "Announces or documents a concrete software release, changelog entry, feature, developer tool/repo/skill, "
        "measured benchmark result, model launch, or reproducible agent engineering workflow."
    ),
    "false": (
        "Opinion essay, vague praise ('Mind blown'), subjective complaint ('videos feel the same'), "
        "end-user showcase without a reusable developer tool/repo, hype/doomer thread, beginner question, "
        "or unverified rumor."
    ),
}

VIDEO_CANDIDATE_INSTRUCTIONS = (
    "Could this item be a strong YouTube Short or Long video topic for 'DIY Smart Code' "
    "(which covers hidden Claude Code / Gemini / agent flags & tricks, cost/usage-limit survival tactics, "
    "two-camp tool debates like X vs Y, viral agent skills/repos, and local LLM hardware reality checks)?"
)

VIDEO_CANDIDATE_CRITERIA = [
    "Level 0: Not a video topic (internal patch, minor bugfix, or generic industry news).",
    "Level 1: Minor update or background item — useful for my own repo maintenance, not a standalone video.",
    "Level 2: Solid standalone Short or Long video topic — a new model release, viral agent repo/skill, or notable workflow change viewers can run.",
    "Level 3: High-conviction video hit — reveals a hidden CLI flag/env-var/hook trick not widely known, a cost/usage-limit/loss angle, a sharp X vs Y debate angle, or a local GPU/hardware benchmark.",
]


def route_decision(relevance: float, new_prob: float) -> str:
    """Route item based on PROFILE.md thresholds:
    - drop when relevance < 0.4 OR new <= 0.1
    - keep when relevance >= 0.5 AND new >= 0.6
    - unsure for everything else
    """
    if relevance < 0.4 or new_prob <= 0.1:
        return "drop"
    if relevance >= 0.5 and new_prob >= 0.6:
        return "keep"
    return "unsure"


def _format_item_state(item: SignalItem) -> str:
    domain = urlparse(item.url).netloc if item.url else item.source
    body_excerpt = (item.body or "")[:1200]
    return f"Source: {item.source} ({domain})\nTitle: {item.title}\nURL: {item.url}\nBody:\n{body_excerpt}"


async def _score_item_jev(
    client: httpx.AsyncClient,
    api_key: str,
    item: SignalItem,
    model: str = "typesafe/jev-1.13",
) -> dict[str, Any] | None:
    """Call TypeSafe Jev on OpenRouter `/api/alpha/decisions` with all 3 questions."""
    payload = {
        "model": model,
        "state": _format_item_state(item),
        "questions": {
            "relevance": {
                "type": "score",
                "instructions": RELEVANCE_INSTRUCTIONS,
                "criteria": RELEVANCE_CRITERIA,
            },
            "new": {
                "type": "noul",
                "instructions": NEW_INSTRUCTIONS,
                "criteria": NEW_CRITERIA,
            },
            "video_candidate": {
                "type": "score",
                "instructions": VIDEO_CANDIDATE_INSTRUCTIONS,
                "criteria": VIDEO_CANDIDATE_CRITERIA,
            },
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    for attempt in range(2):
        try:
            resp = await client.post(
                "https://openrouter.ai/api/alpha/decisions",
                json=payload,
                headers=headers,
                timeout=5.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                answers = data.get("answers") or {}
                rel_obj = answers.get("relevance") or {}
                new_obj = answers.get("new") or {}
                vid_obj = answers.get("video_candidate") or {}
                raw_score = float(rel_obj.get("score", 2.0))
                relevance = max(0.0, min(1.0, raw_score / (len(RELEVANCE_CRITERIA) - 1)))
                new_prob = float(new_obj.get("noul", 0.5))
                vid_level = float(vid_obj.get("score", 1.0))
                vid_score = max(0.0, min(1.0, vid_level / (len(VIDEO_CANDIDATE_CRITERIA) - 1)))
                route = route_decision(relevance, new_prob)
                return {
                    "relevance": round(relevance, 3),
                    "relevance_level": round(raw_score, 2),
                    "new": round(new_prob, 3),
                    "video_score": round(vid_score, 3),
                    "video_level": round(vid_level, 2),
                    "route": route,
                    "model": model,
                }
            if resp.status_code in (404, 400, 401, 403):
                return None
            if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                await asyncio.sleep(0.5)
                continue
        except Exception:
            if attempt == 0:
                await asyncio.sleep(0.3)
                continue
    return None


async def _score_item_llm_fallback(
    client: httpx.AsyncClient,
    api_key: str,
    item: SignalItem,
    fallback_model: str = "google/gemini-2.5-flash-lite",
) -> dict[str, Any]:
    """Structured JSON fallback on OpenRouter `/api/v1/chat/completions` if Jev endpoint is unavailable."""
    system_prompt = (
        "You are a fast, calibrated decision classifier. Answer three independent questions about the item "
        "and return ONLY valid JSON: {\"relevance_level\": <float 0.0 to 4.0>, \"new_prob\": <float 0.0 to 1.0>, \"video_level\": <float 0.0 to 3.0>}.\n\n"
        f"Question 1 (relevance_level 0..4): {RELEVANCE_INSTRUCTIONS}\n"
        + "\n".join(RELEVANCE_CRITERIA)
        + f"\n\nQuestion 2 (new_prob 0..1): {NEW_INSTRUCTIONS}\n"
        f"- 1.0 (true): {NEW_CRITERIA['true']}\n"
        f"- 0.0 (false): {NEW_CRITERIA['false']}\n\n"
        f"Question 3 (video_level 0..3): {VIDEO_CANDIDATE_INSTRUCTIONS}\n"
        + "\n".join(VIDEO_CANDIDATE_CRITERIA)
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": fallback_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _format_item_state(item)},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        raw_level = float(parsed.get("relevance_level", 2.0))
        relevance = max(0.0, min(1.0, raw_level / 4.0))
        new_prob = max(0.0, min(1.0, float(parsed.get("new_prob", 0.5))))
        vid_level = max(0.0, min(3.0, float(parsed.get("video_level", 1.0))))
        vid_score = vid_level / 3.0
        route = route_decision(relevance, new_prob)
        return {
            "relevance": round(relevance, 3),
            "relevance_level": round(raw_level, 2),
            "new": round(new_prob, 3),
            "video_score": round(vid_score, 3),
            "video_level": round(vid_level, 2),
            "route": route,
            "model": fallback_model,
        }
    except Exception as exc:
        return {
            "relevance": 0.5,
            "relevance_level": 2.0,
            "new": 0.5,
            "video_score": 0.33,
            "video_level": 1.0,
            "route": "unsure",
            "model": "fallback-error",
            "error": str(exc)[:120],
        }


async def score_items_parallel(
    items: list[SignalItem],
    concurrency: int = 12,
    force_llm_model: str | None = None,
) -> tuple[list[tuple[SignalItem, dict[str, Any]]], float]:
    """Score a batch of items concurrently (8-16 in flight). Returns ((item, decision), elapsed_sec)."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set in .env. Please add it to your .env file."
        )

    jev_model = os.environ.get("DECISION_MODEL", "typesafe/jev-1.13").strip()
    fallback_model = (
        force_llm_model
        or os.environ.get("DECISION_FALLBACK_MODEL", "google/gemini-2.5-flash-lite").strip()
    )

    sem = asyncio.Semaphore(concurrency)
    t0 = time.perf_counter()

    async with httpx.AsyncClient() as client:
        async def _worker(it: SignalItem) -> tuple[SignalItem, dict[str, Any]]:
            async with sem:
                if not force_llm_model:
                    res = await _score_item_jev(client, api_key, it, model=jev_model)
                    if res is not None:
                        return it, res
                res = await _score_item_llm_fallback(
                    client, api_key, it, fallback_model=fallback_model
                )
                return it, res

        results = await asyncio.gather(*[_worker(it) for it in items])

    elapsed = time.perf_counter() - t0
    return list(results), elapsed


# Interview + Live-Sorted Today Keep/Drop Benchmark Examples (Stage 4 verification set)
INTERVIEW_EXAMPLES: list[tuple[str, SignalItem]] = [
    (
        "keep",
        SignalItem(
            id="ex:keep1",
            source="claude-code",
            title="Claude Code v2.1.302: Added CLAUDE_CODE_AUTO_MODE_MODEL and prompt decoration virtualText",
            url="https://github.com/anthropics/claude-code/releases/tag/v2.1.302",
            body="Release v2.1.302 adds CLAUDE_CODE_AUTO_MODE_MODEL environment variable to configure client-side auto mode classifier model and virtualText prompt decorations.",
        ),
    ),
    (
        "keep",
        SignalItem(
            id="ex:keep2",
            source="hyperframes",
            title="HyperFrames v0.8.167 & feat(producer): distributed renders accept 25 fps and 720p/480p render routes",
            url="https://github.com/heygen-com/hyperframes/releases/tag/v0.8.167",
            body="Long projects preview more smoothly: preview work now follows what is playing, not total clip count. Producer supports distributed 25fps and 720p/480p renders.",
        ),
    ),
    (
        "keep",
        SignalItem(
            id="ex:keep3",
            source="gemini-cli",
            title="Gemini CLI v0.66.0-nightly.20261017: Add Banner about Gemini CLI not being optimized for Gemini 4",
            url="https://github.com/google-gemini/gemini-cli/pull/29774",
            body="Nightly release v0.66.0-nightly.20261017 adds notice regarding Gemini 4 optimization in Gemini CLI.",
        ),
    ),
    (
        "keep",
        SignalItem(
            id="ex:keep4",
            source="reddit",
            title="[r/ClaudeAI] I have put jev inside claude code's harness to reduce token maxing",
            url="https://www.reddit.com/r/ClaudeAI/comments/jev_harness",
            body="Built a hook/harness integration using TypeSafe's Jev decision model inside Claude Code to pre-filter context and tool outputs, cutting token usage significantly.",
        ),
    ),
    (
        "keep",
        SignalItem(
            id="ex:keep5",
            source="hacker-news",
            title="Show HN: Llmspeed – feel how fast a local LLM runs before you buy the hardware",
            url="https://news.ycombinator.com/item?id=llmspeed",
            body="Interactive benchmark tool showing token/s latency and throughput across GPUs and Apple Silicon for local open-weight LLMs.",
        ),
    ),
    (
        "drop",
        SignalItem(
            id="ex:drop1",
            source="reddit",
            title="[r/ClaudeAI] Mind blown by Claude",
            url="https://www.reddit.com/r/ClaudeAI/comments/mind_blown",
            body="I just started using Claude this week and I am completely mind blown by how good it is compared to everything else!",
        ),
    ),
    (
        "drop",
        SignalItem(
            id="ex:drop2",
            source="reddit",
            title="[r/ClaudeAI] The new Opus generated videos all feel the same.",
            url="https://www.reddit.com/r/ClaudeAI/comments/opus_videos",
            body="Does anyone else feel like all the videos people are generating with Opus have the exact same style and pacing? Getting tired of seeing them.",
        ),
    ),
    (
        "drop",
        SignalItem(
            id="ex:drop3",
            source="reddit",
            title="[r/ClaudeAI] I made my first game: A multiplayer RTS. Today is the 7th day working on it.",
            url="https://www.reddit.com/r/ClaudeAI/comments/rts_game",
            body="Here is a video of my multiplayer RTS game that I have been vibe coding for the past 7 days! Let me know what you think of the graphics.",
        ),
    ),
    (
        "drop",
        SignalItem(
            id="ex:drop4",
            source="hacker-news",
            title="AI Startup Raises $400M Series B at $4B Valuation Amid Investor Frenzy",
            url="https://example.com/ai-funding-news",
            body="Venture capital firms continue pouring billions into generative AI startups as valuations soar, according to people familiar with the matter.",
        ),
    ),
]
