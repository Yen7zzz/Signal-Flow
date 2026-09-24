# ============================================================
# pipeline_a_transformer.py — 每天執行：抓新聞 → Transformer 篩選 → 存 DB
#
# 跟原本 pipeline_a.py 的差別：
# 舊版：存所有文章進 DB，讓 GPT 自己篩
# 新版：先用 Transformer 判斷語意分類，低於門檻的文章存為「未分類」（不抓全文）
# ============================================================

import feedparser
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from database import init_db, save_article, article_exists, update_full_text
from classifier import NewsClassifier
from scraper import fetch_full_text
from cleanup_fulltext import clear_old_fulltext
from config import (
    RSS_FEEDS, TITLE_BLOCKLIST, TITLE_BLOCKLIST_PATTERNS, FULLTEXT_RETENTION_DAYS,
    CLASSIFIER_THRESHOLD, UNCLASSIFIED_CATEGORY,
)
import os

os.makedirs("logs", exist_ok=True)  # 加這行

logging.basicConfig(
    filename="logs/pipeline_a.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


def is_blocklisted_title(title: str) -> bool:
    """標題是否命中黑名單（純字串或 regex），命中視為內容農場/導購頁面"""
    title_lower = title.lower()
    if any(keyword in title_lower for keyword in TITLE_BLOCKLIST):
        return True
    if any(re.search(pattern, title_lower) for pattern in TITLE_BLOCKLIST_PATTERNS):
        return True
    return False


def parse_feed(category: str, feed_url: str) -> tuple[list[dict], int]:
    """解析單一 RSS feed，回傳（文章清單, 黑名單擋掉篇數）"""
    try:
        feed = feedparser.parse(feed_url)
        articles = []
        blocked_count = 0
        for entry in feed.entries:
            title     = entry.get("title", "").strip()
            url       = entry.get("link", "").strip()
            summary   = re.sub(r"<[^>]+>", "", entry.get("summary", ""))[:500]
            published = entry.get("published", "")

            if title and url:
                if is_blocklisted_title(title):
                    blocked_count += 1
                    print(f"      🚫 黑名單擋掉：{title[:60]}")
                    continue
                articles.append({
                    "category":  category,   # RSS 設定的分類（後面會被 Transformer 覆蓋）
                    "title":     title,
                    "url":       url,
                    "summary":   summary,
                    "source":    feed.feed.get("title", feed_url),
                    "published": published,
                })
        if blocked_count:
            print(f"      🚫 {feed_url[:50]}... 共擋掉 {blocked_count} 篇黑名單標題")
        return articles, blocked_count
    except Exception as e:
        logging.error(f"❌ 解析失敗 {feed_url}: {e}")
        return [], 0


def run():
    print(f"\n{'='*50}")
    print(f"🗞️  Pipeline A (Transformer版) — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    init_db()

    # 載入 Transformer 模型（只載入一次，所有分類共用）
    classifier = NewsClassifier()

    total_fetched      = 0   # 通過黑名單後的文章數
    total_blocked      = 0   # 黑名單擋掉
    total_existing     = 0   # 已在 DB（含同一輪其他 feed 已存過的重複 URL）
    total_classified   = 0   # 新存入，正常分類
    total_unclassified = 0   # 新存入，低於門檻歸入「未分類」
    newly_saved_urls = []   # 收集本次新存入且正常分類的 URL，供全文抓取使用（未分類不抓全文）

    for category, feed_urls in RSS_FEEDS.items():
        print(f"\n📂 分類：{category}")

        # Step 1：抓所有 RSS 文章
        raw_articles = []
        for url in feed_urls:
            articles, blocked = parse_feed(category, url)
            raw_articles.extend(articles)
            total_blocked += blocked
            print(f"   📥 抓到 {len(articles)} 篇 from {url[:50]}...")

        total_fetched += len(raw_articles)
        print(f"\n   🔍 Transformer 語意分類中（threshold={CLASSIFIER_THRESHOLD}，低於門檻存為「{UNCLASSIFIED_CATEGORY}」）...")

        # Step 2：只對 DB 裡還沒有的文章分類，再存入資料庫
        # 注意：這裡不限制在原本的 category，讓 Transformer 重新判斷
        # 有時候一篇「台積電財報」放在科技 RSS，但 Transformer 會同時標記財經
        for article in raw_articles:
            if article_exists(article["url"]):
                total_existing += 1
                continue

            text = f"{article['title']}. {article['summary']}"
            result = classifier.classify(text, CLASSIFIER_THRESHOLD)
            is_relevant = result["is_relevant"]
            saved = save_article(
                category  = result["category"] if is_relevant else UNCLASSIFIED_CATEGORY,
                title     = article["title"],
                url       = article["url"],
                summary   = article["summary"],
                source    = article["source"],
                published = article["published"],
            )
            if not saved:
                total_existing += 1
                continue

            if is_relevant:
                total_classified += 1
                newly_saved_urls.append(article["url"])
                print(f"  ✅ [{result['score']:.2f}] {result['category']}：{article['title'][:50]}...")
            else:
                total_unclassified += 1
                print(f"  ❔ [{result['score']:.2f}] {UNCLASSIFIED_CATEGORY}：{article['title'][:50]}...")

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

    # ── Step 5：清空超過 N 天前的 full_text（只 UPDATE，不 VACUUM）──
    # VACUUM 會重寫整個檔案，導致每天的 git blob 無法 delta 壓縮，
    # 因此只在每日 pipeline 做欄位清空，VACUUM 留給 cleanup_fulltext.py 手動執行
    try:
        cleared = clear_old_fulltext(FULLTEXT_RETENTION_DAYS)
        print(f"\n🧹 已清空 {cleared} 筆超過 {FULLTEXT_RETENTION_DAYS} 天的 full_text")
        logging.info(f"full_text 清理：清空 {cleared} 筆（保留窗口 {FULLTEXT_RETENTION_DAYS} 天）")
    except Exception as e:
        print(f"⚠️  full_text 清理失敗，略過：{e}")
        logging.warning(f"full_text 清理失敗：{e}")

    print(f"\n{'='*50}")
    print(f"🎉 完成！")
    print(f"   抓到：{total_fetched} 篇（另有黑名單擋掉 {total_blocked} 篇）")
    print(f"   已在 DB：{total_existing} 篇")
    print(f"   新存入：{total_classified} 篇正常分類，{total_unclassified} 篇{UNCLASSIFIED_CATEGORY}")
    logging.info(
        f"Pipeline A 完成，抓 {total_fetched} 篇（黑名單 {total_blocked}），已在 DB {total_existing}，"
        f"新分類 {total_classified}，新{UNCLASSIFIED_CATEGORY} {total_unclassified}"
    )


if __name__ == "__main__":
    run()
