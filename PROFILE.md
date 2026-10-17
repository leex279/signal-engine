# Signal engine profile

<!-- Written by the build-signal-engine interview. Every stage reads this file. Edit it
     freely; the engine follows it. -->

## What I keep up with

New releases, changelogs, skills, workflows, and concrete changes in the AI coding agents, models, and video/browser agent tools I use daily (**Google Antigravity / Gemini**, **Anthropic Claude Code / Claude**, **OpenAI Codex / Cursor**, **BrowserOS Neo / MCP / Local LLMs**, and **HeyGen HyperFrames**), so I can try, adopt, or update them the week they ship.

## Sources

Data platform: **Per-source native free APIs & feeds** (GitHub API, HN Algolia API, Reddit RSS/JSON, YouTube RSS, and Markdown/HTML changelog splitters — $0 scraper bill).

| Source | What it is | How it is pulled | Why it is here |
|---|---|---|---|
| `claude-code` | Anthropic Claude Code releases & changelog | GitHub Releases API (`anthropics/claude-code`) + raw `CHANGELOG.md` | R1.2: Official tool updates & deprecations show up here first |
| `gemini-cli` | Google Gemini CLI & SDK releases | GitHub Releases API (`google-gemini/gemini-cli`) | R2.1: Core daily CLI & model ecosystem |
| `hyperframes` | HeyGen HyperFrames (`heygen-com/hyperframes`) | GitHub Commits/Releases API + Mintlify changelog (`hyperframes.mintlify.app/changelog`) | R2.1: Core agentic video framework used across projects |
| `openai-codex` | OpenAI Codex CLI & agent releases | GitHub Releases API (`openai/codex`) | R2.1: Coding agent & model updates |
| `coleam00-skills` | Cole Medin's Claude/Agent Skills (`coleam00/skills`) | GitHub Commits API (`coleam00/skills`) | R2.2: Reference agent skills and workflows |
| `ollama` | Local LLM runner releases (`ollama/ollama`) | GitHub Releases API (`ollama/ollama`) | R2.1: Local & open-weight model support |
| `official-blogs` | Anthropic, Google AI / Gemini, and OpenAI developer blogs/changelogs | RSS / Atom feeds & Markdown changelog splitter | R1.2 & R2.2: First-party model & API announcements |
| `hacker-news` | Hacker News AI & agent stories | HN Algolia API (`search_by_date`, `points>=15`) | R2.2: Early technical signal and developer repos |
| `reddit` | `r/ClaudeAI`, `r/LocalLLaMA`, `r/singularity`, `r/ChatGPTCoding` | Subreddit top-of-day JSON/RSS feeds (`t=day`, cap 25/sub) | R2.2: Community workarounds, benchmarks, and workflows |
| `youtube-creators` | Cole Medin, IndyDevDan, AI Explained | YouTube native channel RSS feeds (`feeds/videos.xml`) | R2.2: Creator deep-dives on agent architectures and new models |

## Code filters

- **Max age:** 48 hours (`48h` for community/feeds; `7d` on initial changelog seed so recent releases aren't missed on day 1, then `48h` + deduplication by stable ID)
- **Engagement floor:** 15 points/upvotes on community sources (Hacker News, Reddit); exempt for first-party changelogs, GitHub releases, and subscribed YouTube creator feeds
- **Language:** English only (drop non-English items in code)
- **Deduplication:** Stable ID check in SQLite before any decision or LLM call

## The decision question(s)

1. **Relevance (score 0–4):**
   - `0`: Unrelated to AI software engineering, coding agents, LLMs, browser automation, or programmatic video.
   - `1`: General AI news, funding/valuation drama, policy, or consumer chat fluff that does not affect how a builder works.
   - `2`: Adjacent AI developer topic, general tutorial, or minor discussion without immediate impact on my stack.
   - `3`: Useful workflow, benchmark shift, open-weight model release, MCP server, or agent architecture I can learn from or steal.
   - `4`: Direct release, changelog update, new capability, skill, or breaking change in my core stack (Antigravity, Gemini, Claude Code, HyperFrames, BrowserOS, OpenAI/Codex, MCP, Ollama). *(Note: an unfamiliar new tool or model name is not a reason to score lower if it solves one of these problems.)*

2. **Reports something new and concrete (yes/no `noul`):**
   - `true`: Announces or documents a concrete release, changelog entry, feature, open-source repo/skill, measured benchmark, technical postmortem, or reproducible workflow.
   - `false`: Opinion essay, hype/doomer thread ("AI will replace X"), beginner question, customer support/billing complaint, meme, or unverified rumor.

Routing: **drop** when `relevance < 0.4` OR `new <= 0.1`; **keep** when `relevance >= 0.5` AND `new >= 0.6`; **unsure** for everything else (sent to the reading pass so nothing big is missed — R2.5).

### Keep examples
- `[claude-code]` v2.1.302 (`CLAUDE_CODE_AUTO_MODE_MODEL`) & v2.1.300 (`virtualText` prompt decorations).
- `[hyperframes]` v0.8.167 smoother preview & `feat(producer)` distributed renders (25fps, 720p/480p render routes).
- `[gemini-cli]` v0.66.0-nightly (Gemini 4 banner) & `[openai-codex]` rust-v0.164.0-alpha.3.
- `[r/ClaudeAI]` "I have put jev inside claude code's harness to reduce token maxing" & `[hacker-news]` "Show HN: Llmspeed – feel how fast a local LLM runs before you buy the hardware".

### Drop examples
- `[r/ClaudeAI]` "Mind blown by Claude" (vague praise post with no concrete workflow or release).
- `[r/ClaudeAI]` "The new Opus generated videos all feel the same" (subjective complaint/opinion thread).
- `[r/ClaudeAI]` "I made my first game: A multiplayer RTS. Today is the 7th day working on it" (unrelated game showcase, not an agent/developer workflow or tool change).
- Generic AI funding/valuation news, "AI will replace developers" debates, and rate-limit complaints.

## The digest

- **Where I read it:** Markdown file in the repo (`digests/YYYY-MM-DD.md`), opened in VS Code / Obsidian.
- **Length cap:** 10 items max.
- **Format:**
  ```markdown
  # YYYY-MM-DD - <one line on what mattered today>

  ## Releases & Changelogs
  - **<Item in plain words>** - 1-2 sentences on what changed and why it matters to your stack. [source](url)

  ## Agent Workflows, Repos & Models
  - **<Item in plain words>** - 1-2 sentences on what is new and actionable. [source](url)

  ## Also worth a look
  - One-liners with [links](url)
  ```
- **Extras:** None required by default (audit stats footer included at bottom of digest).

## Schedule

- **Full run:** Daily at 07:00 local time (via OpenRouter: `typesafe/jev-1.13` for the decision pass, mid-tier LLM for the reading pass).
- **Shadow week:** Starts `2026-10-17`
