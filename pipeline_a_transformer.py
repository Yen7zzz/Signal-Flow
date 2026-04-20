# ============================================================
# pipeline_a_transformer.py — 每天執行：抓新聞 → Transformer 篩選 → 存 DB
#
# 跟原本 pipeline_a.py 的差別：
# 舊版：存所有文章進 DB，讓 GPT 自己篩
# 新版：先用 Transformer 判斷語意相關性，只存通過的文章
# ============================================================

import feedparser
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from database import init_db, save_article, article_exists, update_full_text
from classifier import NewsClassifier
from scraper import fetch_full_text
from config import RSS_FEEDS
import os

os.makedirs("logs", exist_ok=True)  # 加這行

logging.basicConfig(
    filename="logs/pipeline_a.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ── 重要設定 ──────────────────────────────────────────────────
# 信心分數門檻：
#   0.3 → 寬鬆，保留多，但可能有雜訊
#   0.4 → 平衡，推薦預設值
#   0.6 → 嚴格，保留少，但精準
#
# 建議先用 0.3 跑一次，看看輸出，再逐步調高
THRESHOLD = 0.4


def parse_feed(category: str, feed_url: str) -> list[dict]:
    """解析單一 RSS feed，回傳文章清單"""
    try:
        feed = feedparser.parse(feed_url)
        articles = []
        for entry in feed.entries:
            title     = entry.get("title", "").strip()
            url       = entry.get("link", "").strip()
            summary   = re.sub(r"<[^>]+>", "", entry.get("summary", ""))[:500]
            published = entry.get("published", "")

            if title and url:
                articles.append({
                    "category":  category,   # RSS 設定的分類（後面會被 Transformer 覆蓋）
                    "title":     title,
                    "url":       url,
                    "summary":   summary,
                    "source":    feed.feed.get("title", feed_url),
                    "published": published,
                })
        return articles
    except Exception as e:
        logging.error(f"❌ 解析失敗 {feed_url}: {e}")
        return []


def run():
    print(f"\n{'='*50}")
    print(f"🗞️  Pipeline A (Transformer版) — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    init_db()

    # 載入 Transformer 模型（只載入一次，所有分類共用）
    classifier = NewsClassifier()

    total_fetched = 0
    total_saved   = 0
    newly_saved_urls = []   # 收集本次新存入的 URL，供全文抓取使用

    for category, feed_urls in RSS_FEEDS.items():
        print(f"\n📂 分類：{category}")

        # Step 1：抓所有 RSS 文章
        raw_articles = []
        for url in feed_urls:
            articles = parse_feed(category, url)
            raw_articles.extend(articles)
            print(f"   📥 抓到 {len(articles)} 篇 from {url[:50]}...")

        total_fetched += len(raw_articles)
        print(f"\n   🔍 Transformer 語意篩選中（threshold={THRESHOLD}）...")

        # Step 2：Transformer 篩選
        # 注意：這裡不限制在原本的 category，讓 Transformer 重新判斷
        # 有時候一篇「台積電財報」放在科技 RSS，但 Transformer 會同時標記財經
        relevant_articles = classifier.batch_classify(raw_articles, threshold=THRESHOLD)

        # Step 3：存入資料庫
        for article in relevant_articles:
            if not article_exists(article["url"]):
                saved = save_article(
                    category  = article["category"],   # Transformer 判斷的分類
                    title     = article["title"],
                    url       = article["url"],
                    summary   = article["summary"],
                    source    = article["source"],
                    published = article["published"],
                )
                if saved:
                    total_saved += 1
                    newly_saved_urls.append(article["url"])

    # ── Step 4：並行抓取全文（只針對本次新存入的文章）──────────────
    if newly_saved_urls:
        print(f"\n📄 全文抓取中（{len(newly_saved_urls)} 篇，workers=5）...")
        ft_success = 0
        ft_failure = 0

        def _fetch_and_store(url: str) -> tuple[str, bool]:
            text = fetch_full_text(url)
            if text:
                update_full_text(url, text)
                return url, True
            return url, False

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_fetch_and_store, u): u for u in newly_saved_urls}
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    _, ok = future.result()
                except Exception as e:
                    ok = False
                    logging.warning(f"全文抓取異常 {futures[future]}: {e}")
                if ok:
                    ft_success += 1
                else:
                    ft_failure += 1
                print(f"   [{i}/{len(newly_saved_urls)}] {'✅' if ok else '❌'} {futures[future][:70]}")

        print(f"\n   全文抓取完成：成功 {ft_success} 篇，失敗 {ft_failure} 篇")
        logging.info(f"全文抓取：成功 {ft_success}，失敗 {ft_failure}")

    print(f"\n{'='*50}")
    print(f"🎉 完成！")
    print(f"   抓到：{total_fetched} 篇")
    print(f"   通過篩選：{total_saved} 篇")
    print(f"   過濾掉：{total_fetched - total_saved} 篇雜訊")
    logging.info(f"Pipeline A 完成，抓 {total_fetched} 篇，存 {total_saved} 篇")


if __name__ == "__main__":
    run()
