# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Signal-Flow is a Python automation system that:
1. **Pipeline A** – Daily: Fetches RSS feeds, optionally filters with a Transformer classifier, deduplicates via MD5 hash, stores in SQLite
2. **Pipeline B** – Weekly (Monday): Queries the last 7 days of articles, calls Groq/OpenAI to select top 5 per category and write summaries, sends an HTML digest email via Gmail SMTP

## Setup

```bash
pip install -r requirements.txt
```

All user configuration lives in `config.py` — API keys, email credentials, RSS feed lists, AI provider selection (Groq vs OpenAI), and `TOP_N` articles per category.

For GitHub Actions deployment, `config.py` is generated dynamically from repository secrets (see `weekly_digest.yml`). Required secrets: `GROQ_API_KEY`, `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVERS`.

## Running the Pipelines

```bash
# Daily collection (basic)
python pipeline_a.py

# Daily collection with semantic filtering (recommended)
python pipeline_a_transformer.py

# Weekly digest generation and email send
python pipeline_b.py

# Production scheduler (runs both on cron-like schedule)
python scheduler.py

# Calibrate the Transformer classification threshold
python evaluate_threshold.py
```

## Architecture

| File | Role |
|------|------|
| `config.py` | Single source of truth for all settings |
| `database.py` | SQLite wrapper: init, dedup check, save, query |
| `pipeline_a.py` | RSS fetch → clean HTML → deduplicate → store |
| `pipeline_a_transformer.py` | Pipeline A + zero-shot semantic filtering via `classifier.py` |
| `classifier.py` | Wraps `cross-encoder/nli-MiniLM2-L6-H768` for zero-shot category classification |
| `evaluate_threshold.py` | Shows per-article scores and retention rates to tune `THRESHOLD` |
| `pipeline_b.py` | Query DB → AI summarization per category → build HTML email → send via SMTP |
| `scheduler.py` | Local production entry point using `schedule` library (daily 08:00 + Monday 09:00) |

## Key Design Decisions

- **Database persistence in git**: `data/news.db` is committed so the SQLite DB survives between GitHub Actions runs (daily workflow commits it back after each collection).
- **Pluggable AI backend**: `config.py` has `USE_GROQ = True/False` to switch between Groq (`llama-3.3-70b-versatile`) and OpenAI (`gpt-4o-mini`).
- **Deduplication**: Articles are identified by MD5 hash of their URL — `database.article_exists()` prevents duplicates.
- **Transformer filtering is optional**: `pipeline_a.py` skips it; `pipeline_a_transformer.py` adds a confidence-threshold gate before storing. Use `evaluate_threshold.py` to find the right threshold value.
- **Email summaries are in Chinese**: The AI prompt in `pipeline_b.py` requests 2–3 sentence Chinese summaries. The HTML template uses category icons: 💰 Finance, 🔬 Technology, 🌏 Politics.
