# ============================================================
# config.py — 本地用直接填值，GitHub Actions 用環境變數
# ============================================================
import os
import json

# --- AI 設定 ---
AI_PROVIDER  = "groq"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "gsk_你的key")
GROQ_MODEL   = "llama-3.3-70b-versatile"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = "gpt-4o-mini"

# --- Email 設定 ---
EMAIL_SENDER    = os.environ.get("EMAIL_SENDER", "your@gmail.com")
EMAIL_PASSWORD  = os.environ.get("EMAIL_PASSWORD", "your-app-password")
EMAIL_RECEIVERS = json.loads(os.environ.get("EMAIL_RECEIVERS", '["your@gmail.com"]'))

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# --- 資料庫 ---
DB_PATH = "data/news.db"

# --- 每類 TOP 幾則 ---
TOP_N = 5

# --- RSS 來源 ---
RSS_FEEDS = {
    "Finance": [
        "https://feeds.bloomberg.com/markets/news.rss",
        "https://www.cnbc.com/id/10001147/device/rss/rss.html",
        "https://feeds.reuters.com/reuters/businessNews",
        "https://www.ft.com/rss/home",
    ],
    "Technology": [
        "https://feeds.feedburner.com/TechCrunch",
        "https://www.theverge.com/rss/index.xml",
        "https://hnrss.org/frontpage",
        "https://www.engadget.com/rss.xml",
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://www.wired.com/feed/rss",
        "https://www.technologyreview.com/topnews.rss",
    ],
    "Politics": [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://feeds.reuters.com/reuters/worldNews",
    ],
}