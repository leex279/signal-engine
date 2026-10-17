# Signal engine profile

<!-- Written by the build-signal-engine interview + Claude memory extraction.
     Every stage reads this file. Edit it freely; the engine follows it. -->

## What I keep up with

New releases, changelogs, hidden CLI flags/env-vars, skills, workflows, benchmarks, and model launches across my AI engineering and YouTube production stack (**Google Antigravity / Gemini / Gemma**, **Anthropic Claude Code / Claude API**, **HeyGen HyperFrames**, **OpenAI Codex / Agents SDK**, **Cursor**, **BrowserOS Neo**, **MCP**, **ElevenLabs**, **GSAP**, **n8n**, and **local LLMs on Ollama / llama.cpp / ROCm 7900 XTX**), so I can:
1. Update or adopt changes in my stack the week they ship (including tracking HyperFrames pin drift in `diy-yt-creator-hyperframes`).
2. Spot high-conviction **DIY Smart Code** YouTube Short & Long video candidates before or with a sharper angle than competitors, deduplicated against my 813-video `catalog.json` and `claude-basics/TRACKER.md`.

## Sources

Data platform: **Per-source native free APIs, RSS/Atom feeds, HTML/Markdown changelog splitters, and daily `llms.txt` / model list diffs** ($0 scraper bill).

| Source | What it is | How it is pulled | Why it is here |
|---|---|---|---|
| `claude-code` | Claude Code releases, API release notes, Status incidents (`status.claude.com`), `code.claude.com/docs/llms.txt` diff | GitHub Releases API + HTML splitter + Status RSS + daily `llms.txt` diff | R1.2 & Claude Basics Shorts: flags, env vars, hooks, and usage-limit incidents |
| `antigravity-cursor-browseros` | Google Antigravity changelog, Cursor changelog (`feed_cursor.xml`), BrowserOS (`browseros-ai/BrowserOS`) | HTML splitter + RSS + GitHub Releases API | Core daily IDE & browser agent stack |
| `gemini-cli` | Gemini CLI (`google-gemini/gemini-cli`), `googleapis/python-genai`, Gemini API changelog | GitHub Releases API + HTML splitter | Gemini & Gemma model/CLI changes (Gemma Shorts are #2–3 top videos) |
| `hyperframes` | `heygen-com/hyperframes` releases/commits, `llms.txt` diff, + `package.json` pin-drift check | GitHub API + `llms.txt` snapshot diff + local `package.json` check | Core video production renderer & Studio toolchain |
| `openai-codex` | OpenAI Codex (`openai/codex`) + `openai/openai-agents-python` | GitHub Releases API | Coding agent & SDK updates |
| `coleam00-skills` | `modelcontextprotocol`, `anthropics/skills`, `claude-agent-sdk-python`, `coleam00/skills`, `Archon`, `caveman`, `gstack` | GitHub Releases & Commits API | MCP spec, skills, and agent harness repos |
| `video-toolchain` | ElevenLabs (`elevenlabs-python`, `elevenlabs/skills`, changelog), GSAP (`GSAP`, `gsap-skills`), `n8n`, `yt-dlp`, `ast-grep`, `graphify` | GitHub Releases/Commits API + HTML splitter | Production TTS (`eleven_v4`), animation, automation, and code analysis tools |
| `ollama` | `ollama/ollama` + `ggml-org/llama.cpp` & `whisper.cpp` (filtered to ROCm, Vulkan, and new model architectures) | GitHub Releases API + regex pre-filter | Local LLM runner & 7900 XTX GPU support |
| `github-viral-repos` | Newly created viral repos (`created:>7d stars:>150`) in `claude-code`, `mcp`, `claude skills`, `coding agent`, `llm` | GitHub Search Repositories API | Early detection of breakout agent repos (like `understand-anything`, Karpathy wiki) |
| `model-radar` | OpenRouter `/api/v1/models` daily diff + HuggingFace `/api/models?sort=trendingScore` | OpenRouter & HuggingFace JSON APIs | Day-0 detection of new model IDs and trending open-weight launches (Gemma, Qwen, GLM, Kimi) |
| `official-blogs` | Anthropic Engineering, Claude Blog, OpenAI Developer Changelog, Simon Willison, YouTube Official Blog | RSS / Atom feeds | Engineering deep-dives & YouTube creator policy shifts |
| `hacker-news` | Hacker News AI, agent, MCP, LLM, ElevenLabs, Cursor stories | HN Algolia API (`search_by_date`, `points>=5`) | Early technical discussions and Show HN launches |
| `reddit` | `r/ClaudeAI`, `r/ClaudeCode`, `r/LocalLLaMA`, `r/ChatGPTCoding`, `r/mcp`, `r/google_antigravity`, `r/cursor`, `r/GeminiAI`, `r/elevenlabs`, `r/ollama` | Top-of-day RSS with 2.2s rate-limit spacing & per-subreddit percentile | Community workarounds, token/limit findings, and niche sub signal |
| `youtube-creators` | Competitors (**Cloud Codes**, **The Stack ai**), Creators (Cole Medin, IndyDevDan, AI Explained, Sam Witteveen, Developers Digest, Fireship), First-Party (Anthropic, DeepMind, Google Dev, Creator Insider, vidIQ) | YouTube native channel RSS feeds | Competitor topic radar + creator policy updates |

## Code filters

- **Max age:** 48 hours for community/news feeds; 7 days for changelogs, releases, and YouTube uploads.
- **Engagement floor:** ≥15 points on Hacker News; top 65% daily percentile (`sub_percentile >= 0.35`) per subreddit so niche subs (`r/mcp`, `r/google_antigravity`) are never starved by `r/ClaudeAI` volume.
- **Language:** English only.
- **Deduplication:** Stable ID check in SQLite before any decision or LLM call.

## The decision question(s)

1. **Relevance (`score` 0–4):**
   - `0`: Unrelated to AI engineering, coding agents, LLMs, browser automation, TTS, or programmatic video; or general praise/complaint threads and end-user showcases with no reusable developer workflow.
   - `1`: General AI news, funding/valuation drama, policy debates, or subjective reactions.
   - `2`: Adjacent developer topic or minor internal refactor without actionable impact.
   - `3`: Concrete agent workflow, harness integration, benchmark tool, skill, MCP server, or open-weight model release.
   - `4`: Direct release, changelog update, new flag/env-var, skill, outage/limit change, or breaking change in core stack tools.

2. **Reports something new and concrete (`noul` yes/no):**
   - `true`: Announces or documents a concrete release, changelog entry, feature, developer tool/repo/skill, measured benchmark, model launch, or reproducible workflow.
   - `false`: Opinion essay, vague praise, subjective complaint, end-user game/art showcase, hype thread, or rumor.

3. **Video candidate (`score` 0–3):**
   - `0`: Not a video topic.
   - `1`: Useful for repo maintenance only, not a standalone video.
   - `2`: Solid standalone Short or Long topic (new model release, viral agent repo/skill, or notable workflow change).
   - `3`: High-conviction DIY Smart Code hit — hidden CLI flag/env-var/hook trick, cost/usage-limit survival tactic, sharp X vs Y debate angle, or local GPU hardware benchmark.

Routing: **drop** when `relevance < 0.4` OR `new <= 0.1`; **keep** when `relevance >= 0.5` AND `new >= 0.6`; **unsure** for everything else.

### Keep examples
- `[claude-code]` v2.1.302 (`CLAUDE_CODE_AUTO_MODE_MODEL`) & v2.1.300 (`virtualText` prompt decorations).
- `[hyperframes]` v0.8.167 smoother preview & `feat(producer)` distributed renders (25fps, 720p/480p render routes).
- `[gemini-cli]` v0.66.0-nightly (Gemini 4 banner) & `[openai-codex]` rust-v0.164.0-alpha.3.
- `[r/ClaudeAI]` "I have put jev inside claude code's harness to reduce token maxing" & `[hacker-news]` "Show HN: Llmspeed – feel how fast a local LLM runs before you buy the hardware".

### Drop examples
- `[r/ClaudeAI]` "Mind blown by Claude" (vague praise post with no concrete workflow or release).
- `[r/ClaudeAI]` "The new Opus generated videos all feel the same" (subjective complaint/opinion thread).
- `[r/ClaudeAI]` "I made my first game: A multiplayer RTS. Today is the 7th day working on it" (unrelated game showcase).
- Generic AI funding/valuation news, "AI will replace developers" debates, and rate-limit complaints.

## The digest

- **Where I read it:**
  1. `digests/YYYY-MM-DD.md` in the repo
  2. `D:\Nextcloud\Obsidian\sync\smartcode\Videos\_signals\YYYY-MM-DD.md` in Obsidian (with `[[wikilinks]]` to matching video catalog slugs)
- **Length cap & Quotas:** Max 10 main items (`Releases & Changelogs` + `Agent Workflows, Repos & Models`), max 2 bullets per repo (collapsing consecutive versions), at least 3 slots reserved for workflows/repos/models, plus up to 4 **Video Candidates** and an **Action for my repo** header.

## Schedule

- **Full run:** Daily at 07:00 local time via Windows Task Scheduler (`SignalEngineDaily`).
- **Shadow week:** Starts `2026-10-17` ([SHADOW_WEEK.md](./SHADOW_WEEK.md)).
