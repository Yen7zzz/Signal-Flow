# ============================================================
# pipeline_a.py — 每天執行：抓 RSS 新聞 → 存入資料庫
# ============================================================

import feedparser
import logging
from datetime import datetime
from database import init_db, save_article, article_exists
from config import RSS_FEEDS

logging.basicConfig(
    filename="logs/pipeline_a.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


def parse_feed(category: str, feed_url: str) -> list[dict]:
    """
    解析單一 RSS feed，回傳文章清單
    feedparser 會處理各種 RSS/Atom 格式的差異
    """
    try:
        feed = feedparser.parse(feed_url)
        articles = []

        for entry in feed.entries:
            title     = entry.get("title", "").strip()
            url       = entry.get("link", "").strip()
            summary   = entry.get("summary", "").strip()
            published = entry.get("published", "")

            # 清理 HTML tag（有些 RSS summary 帶 HTML）
            import re
            summary = re.sub(r"<[^>]+>", "", summary)[:500]

            if title and url:
                articles.append({
                    "category":  category,
                    "title":     title,
                    "url":       url,
                    "summary":   summary,
                    "source":    feed.feed.get("title", feed_url),
                    "published": published,
                })

        logging.info(f"📥 {category} | {feed_url} → {len(articles)} 篇")
        return articles

    except Exception as e:
        logging.error(f"❌ 解析失敗 {feed_url}: {e}")
        return []


def run():
    """Pipeline A 主程式"""
    print(f"\n{'='*50}")
    print(f"🗞️  Pipeline A 開始 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    init_db()

    total_new = 0

    for category, feed_urls in RSS_FEEDS.items():
        print(f"\n📂 分類：{category}")
        for url in feed_urls:
            articles = parse_feed(category, url)
            for article in articles:
                # 去重：已存在的不重複寫入
                if not article_exists(article["url"]):
                    saved = save_article(**article)
                    if saved:
                        total_new += 1
                        print(f"   ✅ {article['title'][:60]}...")

    print(f"\n🎉 完成！共新增 {total_new} 篇文章")
    logging.info(f"Pipeline A 完成，新增 {total_new} 篇")


if __name__ == "__main__":
    run()
