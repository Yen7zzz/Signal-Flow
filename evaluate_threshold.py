# ============================================================
# evaluate_threshold.py — 找出最佳 threshold 的工具
#
# 使用方式：
# 1. 先跑一次，看各篇文章的分數分佈
# 2. 人工標記幾篇（相關/不相關）
# 3. 找出 Precision 跟 Recall 的甜蜜點
# ============================================================

from classifier import NewsClassifier
from config import RSS_FEEDS
import feedparser
import re


def fetch_sample(n_per_feed: int = 5) -> list[dict]:
    """從所有 RSS 抓樣本文章"""
    articles = []
    for category, urls in RSS_FEEDS.items():
        for url in urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:n_per_feed]:
                    title   = entry.get("title", "").strip()
                    summary = re.sub(r"<[^>]+>", "", entry.get("summary", ""))[:300]
                    if title:
                        articles.append({
                            "rss_category": category,
                            "title":        title,
                            "summary":      summary,
                            "url":          entry.get("link", ""),
                        })
            except:
                pass
    return articles


def analyze(articles: list[dict], classifier: NewsClassifier):
    """
    印出每篇文章的分類結果和分數
    讓你人工判斷 threshold 要設多少
    """
    print(f"\n{'='*60}")
    print(f"分析 {len(articles)} 篇文章的分類分數")
    print(f"{'='*60}\n")

    results = []
    for article in articles:
        text   = f"{article['title']}. {article['summary']}"
        result = classifier.classify(text, threshold=0)  # threshold=0 全部顯示
        results.append({**article, **result})

    # 依分數排序
    results.sort(key=lambda x: x["score"], reverse=True)

    # 印出結果
    for r in results:
        bar = "█" * int(r["score"] * 20)
        print(f"[{r['score']:.2f}] {bar}")
        print(f"  RSS分類：{r['rss_category']} → Transformer判斷：{r['category']}")
        print(f"  標題：{r['title'][:70]}")
        print(f"  各分類分數：{r['all_scores']}")
        print()

    # 統計不同 threshold 的保留率
    print(f"\n{'='*60}")
    print("不同 threshold 的保留率：")
    print(f"{'='*60}")
    for t in [0.3, 0.4, 0.5, 0.6, 0.7]:
        kept = sum(1 for r in results if r["score"] >= t)
        print(f"  threshold={t} → 保留 {kept}/{len(results)} 篇 ({kept/len(results)*100:.0f}%)")


if __name__ == "__main__":
    print("📥 抓取樣本文章...")
    articles = fetch_sample(n_per_feed=5)
    print(f"✅ 抓到 {len(articles)} 篇\n")

    print("🔄 載入 Transformer 模型...")
    classifier = NewsClassifier()

    analyze(articles, classifier)
    
    print("\n💡 建議：")
    print("  看上面的結果，找出分數的自然斷點")
    print("  相關文章都落在某個分數以上")
    print("  不相關文章都落在某個分數以下")
    print("  那個斷點就是你的 threshold")
