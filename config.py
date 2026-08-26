import os

GROQ_API_KEY      = os.environ.get("GROQ_API_KEY", "")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")

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
        "https://www.ft.com/rss/home",
        "https://www.digitimes.com/rss/daily.xml",
        "https://www.federalreserve.gov/feeds/press_all.xml",
    ],
    "Technology": [
        "https://www.theverge.com/rss/index.xml",
        "https://hnrss.org/frontpage?points=200",
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

# ── 來源分級（依報導性質分類，非品質評分）──
# T1 = 通訊社／即時財經（一手事實）
# T2 = 主流報紙／廣電（有採訪，含編輯觀點）
# T3 = 專業媒體／評論／聚合站（多為二手或分析）
SOURCE_TIERS = {
    # Tier 1
    "bloomberg": 1,
    "international homepage": 1,   # FT 的 feed title
    "ft.com": 1,
    "reuters": 1,
    "frb": 1,                      # Fed 官方新聞稿，feed title = "FRB: Press Release - All Releases"

    # Tier 2
    "nyt": 2,                      # 涵蓋 "NYT > World News"
    "new york times": 2,
    "bbc": 2,
    "business news": 2,            # CNBC 的 feed title
    "cnbc": 2,
    "digitimes": 2,                # 供應鏈專業媒體，有一手採訪

    # Tier 3
    "wired": 3,
    "ars technica": 3,
    "technology review": 3,
    "the verge": 3,
    "engadget": 3,
    "hacker news": 3,
}
SOURCE_TIER_DEFAULT = 3   # 未列出的來源預設值

NOVELTY_THRESHOLD = 0.55   # cosine 相似度，超過視為「上週延續事件」

CLUSTER_DISTANCE_THRESHOLD = 0.40   # 校準結果，對應 cosine similarity 0.60
GITHUB_DIGEST_BASE_URL = "https://github.com/Yen7zzz/Signal-Flow/blob/main/digests/"

# 標題黑名單：命中者視為內容農場/導購頁面，於 Transformer 分類前先行過濾

# 純字串比對（小寫）
TITLE_BLOCKLIST = [
    "promo code", "coupon", "discount code",
    "deals of the", "best deals",
]

# regex 比對（處理 "20% Off" / "$250 Off" 這類導購標題）
TITLE_BLOCKLIST_PATTERNS = [
    r"\d+%\s*off",
    r"\$\d+\s*off",
]