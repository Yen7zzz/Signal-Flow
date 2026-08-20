# ============================================================
# novelty.py — 新舊事件標記模組
#
# 對 clusterer.cluster_articles() 的輸出，比對上週週報標題，
# 標記每個事件是「新出現」還是「上週延續」。
# ============================================================

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

import config

_MODEL_NAME = "all-MiniLM-L6-v2"
_model = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"🔄 載入 SentenceTransformer 模型：{_MODEL_NAME}")
        _model = SentenceTransformer(_MODEL_NAME)
        print("✅ 模型載入完成")
    return _model


def mark_novelty(events: list[dict], last_titles: list[str],
                  threshold: float = None) -> list[dict]:
    """
    對每個 event 的 representative title 與 last_titles 做 embedding 比對，
    在 event dict 內原地新增 is_new / novelty_score 兩個欄位。

    Args:
        events:      clusterer.cluster_articles() 的輸出
        last_titles: 上週該分類的事件標題列表
        threshold:   cosine 相似度門檻，超過視為「上週延續事件」；None 則讀 config.NOVELTY_THRESHOLD

    Returns:
        同一個 events list（原地修改後回傳）
    """
    if threshold is None:
        threshold = config.NOVELTY_THRESHOLD

    if not events:
        return events

    if not last_titles:
        for event in events:
            event["is_new"] = True
            event["novelty_score"] = 0.0
        return events

    model = _get_model()

    this_week_titles = [
        event.get("representative", {}).get("title", "") for event in events
    ]

    this_week_embeddings = model.encode(this_week_titles, show_progress_bar=False)
    last_week_embeddings = model.encode(last_titles, show_progress_bar=False)

    # shape: (n_this_week, n_last_week)
    sims = cosine_similarity(this_week_embeddings, last_week_embeddings)
    max_sims = sims.max(axis=1)

    for event, score in zip(events, max_sims):
        score = float(score)
        event["novelty_score"] = score
        event["is_new"] = score <= threshold

    return events


if __name__ == "__main__":
    from database import get_recent_articles, get_last_digest_titles
    from clusterer import NewsClusterer

    articles = get_recent_articles(days=7)
    print(f"📥 撈到 {len(articles)} 篇文章（近 7 天）")

    clusterer = NewsClusterer()

    categories = sorted(set(a["category"] for a in articles))
    for category in categories:
        cat_articles = [a for a in articles if a["category"] == category]
        if not cat_articles:
            continue

        print(f"\n{'=' * 60}")
        print(f"分類：{category}（{len(cat_articles)} 篇）")
        print("=" * 60)

        events = clusterer.cluster_articles(cat_articles)
        last_titles = get_last_digest_titles(category)
        print(f"  上週標題數：{len(last_titles)}")

        events = mark_novelty(events, last_titles)
        events.sort(key=lambda e: e["novelty_score"], reverse=True)

        for e in events:
            title = e.get("representative", {}).get("title", "(無標題)")
            print(f"  [{'延續' if not e['is_new'] else '新'}] "
                  f"score={e['novelty_score']:.3f}  {title}")
