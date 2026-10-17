# Signal Engine

A personal signal engine built around [PROFILE.md](./PROFILE.md). Every morning it pulls from first-party changelogs, GitHub releases, communities, and creator feeds, deduplicates on stable IDs in SQLite, applies factual code filters, runs a fast typed decision pass (`typesafe/jev-1.13` via OpenRouter) on every surviving item, and has an LLM write one concise daily digest in `digests/YYYY-MM-DD.md`.

## Pipeline Architecture

```text
sources -> store (dedupe, stable ids) -> code filters (dates, numbers, language)
        -> decision pass (typed relevance + concrete-new check)
        -> reading pass (LLM groups & summarizes top <=10)
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
