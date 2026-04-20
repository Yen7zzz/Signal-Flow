# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SignalFlow is an automated RSS news aggregation and AI-powered weekly digest system. It collects news from 13+ RSS feeds daily (Finance, Technology, Politics categories), clusters similar articles, uses a dual-model Anthropic setup to summarize and rank stories, and emails HTML digests every Monday morning (TST).

**AI backend:** Anthropic dual-model pipeline — Stage 1 uses `claude-haiku-4-5-20251001` (cost-efficient batch summarization), Stage 2 uses `claude-sonnet-4-6` (quality ranking and trend analysis).

## Setup

```bash
pip install -r requirements.txt
```

Credentials are loaded from environment variables (configured in `config.py` via `os.environ`):
- `ANTHROPIC_API_KEY` — required; drives both Stage 1 and Stage 2
- `EMAIL_SENDER`, `EMAIL_PASSWORD` (Gmail App Password), `EMAIL_RECEIVERS` (comma-separated) — required
- `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY` — retained in config.py but not required by current pipelines

## Running the Pipelines

```bash
# Daily: fetch RSS feeds and store articles
python pipeline_a.py                # basic version
python pipeline_a_transformer.py    # with semantic classification (recommended)

# Weekly: generate AI summary and send HTML email
python pipeline_b.py

# Background scheduler (runs A daily at 08:00, B every Monday at 09:00)
python scheduler.py

# Utilities
python evaluate_threshold.py        # tune Transformer classification threshold
python diagnose_fulltext.py         # diagnose full-text scraping coverage
python test_scraper.py              # test scraper on sample URLs
python test_track_topics.py         # test topic signal tracking
```

## Architecture

**Two-stage pipeline:**

**Pipeline A** (daily ingestion):
RSS feeds → feedparser → Transformer zero-shot classifier (`cross-encoder/nli-MiniLM2-L6-H768`) → MD5 deduplication → SQLite → full-text scraping (trafilatura / newspaper3k fallback)

**Pipeline B** (weekly output):
SQLite (last 7 days) → AgglomerativeClustering (`all-MiniLM-L6-v2`, distance_threshold=0.55) → Stage 1: batch article summarization (Haiku) → Stage 2: ranking + trend analysis (Sonnet) → HTML email via Gmail SMTP

**Key files:**
- `config.py` — central config: AI provider, credentials, feed URLs, `DB_PATH`, `TOP_N`
- `database.py` — SQLite abstraction; deduplication uses MD5 hash of URL stored in `hash` column
- `classifier.py` — Hugging Face zero-shot classifier (`cross-encoder/nli-MiniLM2-L6-H768`); uses English category labels for multilingual model compatibility
- `clusterer.py` — AgglomerativeClustering on sentence embeddings (`all-MiniLM-L6-v2`) to group related articles
- `scraper.py` — full-text extraction via trafilatura with newspaper3k fallback
- `pipeline_a.py` — basic RSS fetch → clean HTML → deduplicate → store
- `pipeline_a_transformer.py` — extends `pipeline_a.py` with classifier filtering and full-text scraping before DB insert
- `pipeline_b.py` — cluster → Stage 1 Haiku summarization → Stage 2 Sonnet ranking/trends → build HTML → send via SMTP
- `scheduler.py` — local production entry point using `schedule` library
- `diagnose_fulltext.py` — diagnostic tool for full-text scraping coverage
- `test_scraper.py` — scraper unit tests
- `test_track_topics.py` — topic signal tracking tests
- `evaluate_threshold.py` — shows per-article scores and retention rates to tune `THRESHOLD`

## CI/CD (GitHub Actions)

- `.github/workflows/daily_collect.yml` — runs `pipeline_a_transformer.py` at UTC 22:00 daily, then auto-commits updated `data/news.db` to main
- `.github/workflows/weekly_digest.yml` — runs `pipeline_b.py` every Sunday at UTC 22:00 (= Taiwan Monday 06:00)

Secrets required in GitHub repo: `ANTHROPIC_API_KEY`, `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVERS`, `GEMINI_API_KEY` (in workflow env; not currently required by pipelines).

## Database Schema

```sql
CREATE TABLE articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash TEXT UNIQUE,       -- MD5(URL) for deduplication
    category TEXT NOT NULL, -- Finance / Technology / Politics
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT NOT NULL,
    source TEXT,
    published TEXT,
    full_text TEXT,         -- scraped full article body
    created_at TEXT DEFAULT (datetime('now'))
)

CREATE TABLE weekly_digests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date   TEXT NOT NULL,
    category   TEXT NOT NULL,
    trend      TEXT,
    articles   TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)

CREATE TABLE topic_signals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date   TEXT NOT NULL,
    topic      TEXT NOT NULL,
    hit_count  INTEGER DEFAULT 0,
    hit_urls   TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)
```

The database file `data/news.db` is committed to the repository and updated daily by GitHub Actions.
