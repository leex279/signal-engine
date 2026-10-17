# Signal Engine

A personal signal engine built around [PROFILE.md](./PROFILE.md). Every morning it pulls from first-party changelogs, GitHub releases, communities, and creator feeds, deduplicates on stable IDs in SQLite, applies factual code filters, runs a fast typed decision pass (`typesafe/jev-1.13` via OpenRouter) on every surviving item, and has an LLM write one daily digest in `digests/YYYY-MM-DD.md`. The digest is a video-topic editor: ranked **Top Video Picks** (hook, format, proof to capture, dedup status) first, then a short stack-updates list. Picks are ranked against the channel's own best videos by views, read from `catalog.json`.

## Pipeline Architecture

```text
sources -> store (dedupe, stable ids) -> code filters (dates, numbers, language)
        -> decision pass (typed relevance + concrete-new check)
        -> pools: video picks / stack updates / also seen
        -> reading pass (LLM ranks 3-5 video picks vs. channel winners)
        -> digest (digests/YYYY-MM-DD.md)
```

## Quick Start

1. Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`.
2. Sync dependencies with `uv`:
   ```powershell
   uv sync
   ```
3. Run the full pipeline:
   ```powershell
   uv run signal-engine run
   ```
