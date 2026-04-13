import os

# ── Stage 1（逐篇摘要）：不開 thinking ──
STAGE1_PROVIDER = "anthropic"
STAGE1_MODEL    = "claude-haiku-4-5-20251001"

# ── Stage 2（排名 + 趨勢分析）：重質量 ──
STAGE2_PROVIDER = "anthropic"
STAGE2_MODEL    = "claude-sonnet-4-6"
STAGE2_THINKING = False

GROQ_API_KEY      = os.environ.get("GROQ_API_KEY", "")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

EMAIL_SENDER    = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD  = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVERS = os.environ.get("EMAIL_RECEIVERS", "")  # 逗號分隔字串，例如 "a@gmail.com,b@gmail.com"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
DB_PATH   = "data/news.db"
TOP_N     = 5

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

TRACKED_TOPICS = {
    "AI 晶片": ["AI chip", "semiconductor", "GPU", "AI accelerator", "NPU", "neural processing"],
    "Fed 利率": ["Federal Reserve", "interest rate", "Fed rate", "FOMC", "rate cut", "rate hike", "monetary policy"],
    "台積電":   ["TSMC", "Taiwan Semiconductor", "TSMC earnings", "chip foundry"],
}
TOPIC_SIMILARITY_THRESHOLD = 0.4