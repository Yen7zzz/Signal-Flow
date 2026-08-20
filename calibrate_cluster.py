# ============================================================
# calibrate_cluster.py — 分群門檻校準工具（診斷用，不修改 clusterer.py）
#
# 對「文章數最多的分類」的近 7 天文章，掃描不同 distance_threshold，
# 觀察壓縮率與 cluster_size 分布，用來判斷合理的分群門檻。
# 分類名稱不寫死：先從 DB 查實際存在的 category 值再決定掃描哪個分類。
# 無任何外部 API 呼叫。
# ============================================================

from collections import Counter

import config
from database import get_connection, get_recent_articles
from clusterer import NewsClusterer

THRESHOLDS = [0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
DUMP_THRESHOLD = 0.40
TOP_N_CLUSTERS_TO_DUMP = 5


def get_recent_categories() -> list[str]:
    """近 7 天 articles 表內實際存在的 category 值"""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT DISTINCT category
            FROM articles
            WHERE created_at >= datetime('now', '-7 days')
        """).fetchall()
    return [r[0] for r in rows]


def check_category_consistency(db_categories: list[str]) -> None:
    """檢查 config.py / DB / pipeline_b.py 三處的分類名稱是否一致"""
    config_categories = list(config.RSS_FEEDS.keys())

    with open("pipeline_b.py", encoding="utf-8") as f:
        pipeline_b_src = f.read()
    # pipeline_b.py 用一個 emoji 對照 dict 支援中英文分類名稱，
    # 從中萃取它實際「認得」的分類字串，粗略判斷涵蓋範圍
    pipeline_b_known = [
        cat for cat in (config_categories + db_categories)
        if f'"{cat}"' in pipeline_b_src
    ]

    print(f"\n{'='*70}")
    print("🔍 分類名稱一致性檢查")
    print("=" * 70)
    print(f"  config.py  RSS_FEEDS keys : {config_categories}")
    print(f"  DB         category 實際值: {db_categories}")
    print(f"  pipeline_b.py 內出現的分類 : {pipeline_b_known}")

    if set(config_categories) & set(db_categories):
        print("  ⚠️ config.py 與 DB 有交集 —— 但請注意：RSS_FEEDS 的 key 只是")
        print("     pipeline_a_transformer.py 抓取時的初始分類，實際會被")
        print("     classifier.py 的 Transformer 分類結果覆蓋（見 pipeline_a_transformer.py:100）。")
    else:
        print("  ⚠️ config.py（英文）與 DB（實際值）沒有交集：")
        print("     RSS_FEEDS 只決定抓取時的『初始』分類，實際寫入 DB 的是")
        print("     classifier.py 判斷出的分類（中文：財經/科技/政治），")
        print("     兩者字面不一致，但不影響現有 pipeline 運作，因為")
        print("     pipeline_a_transformer.py 一律以分類器結果覆蓋 RSS 分類。")

    if set(db_categories) - set(pipeline_b_known):
        missing = set(db_categories) - set(pipeline_b_known)
        print(f"  ⚠️ pipeline_b.py 的 emoji 對照表未涵蓋 DB 分類：{missing}")
    else:
        print("  ✅ pipeline_b.py 的 emoji 對照表涵蓋所有 DB 實際分類")
    print("=" * 70)


def summarize_events(events: list[dict]) -> dict:
    sizes = [e["cluster_size"] for e in events]
    size_1 = sum(1 for s in sizes if s == 1)
    size_2_3 = sum(1 for s in sizes if 2 <= s <= 3)
    size_4plus = sum(1 for s in sizes if s >= 4)
    return {
        "n_events": len(events),
        "size_1": size_1,
        "size_2_3": size_2_3,
        "size_4plus": size_4plus,
        "max_size": max(sizes) if sizes else 0,
    }


def dump_top_clusters(events: list[dict], top_n: int) -> None:
    sorted_events = sorted(events, key=lambda e: e["cluster_size"], reverse=True)
    for i, event in enumerate(sorted_events[:top_n], start=1):
        rep = event["representative"]
        related = event["related"]
        print(f"\n  ── 群 #{i}（cluster_size={event['cluster_size']}）──")
        print(f"    [代表] {rep.get('title', '(無標題)')}")
        for r in related:
            print(f"    [相關] {r.get('title', '(無標題)')}")


def main():
    all_articles = get_recent_articles(days=7)
    if not all_articles:
        print("⚠️ 近 7 天無文章，結束")
        return

    db_categories = get_recent_categories()
    print(f"📂 DB 內近 7 天實際存在的 category 值：{db_categories}")

    check_category_consistency(db_categories)

    # 選文章數最多的分類
    counts = Counter(a["category"] for a in all_articles)
    category = counts.most_common(1)[0][0]
    cat_articles = [a for a in all_articles if a["category"] == category]
    n = len(cat_articles)

    print(f"\n📦 各分類文章數：{dict(counts)}")
    print(f"📦 掃描對象：分類「{category}」（文章數最多），共 {n} 篇")

    clusterer = NewsClusterer()

    print(f"\n{'='*70}")
    print(f"{'threshold':>10} | {'sim≈':>6} | {'events':>7} | {'壓縮率':>7} | "
          f"{'size=1':>7} | {'size2-3':>8} | {'size4+':>7} | {'max_size':>8}")
    print("=" * 70)

    dump_events = None
    for dt in THRESHOLDS:
        events = clusterer.cluster_articles(cat_articles, distance_threshold=dt)
        stats = summarize_events(events)
        compression = stats["n_events"] / n if n else 0
        sim_approx = 1 - dt
        print(f"{dt:>10.2f} | {sim_approx:>6.2f} | {stats['n_events']:>7} | "
              f"{compression:>6.1%} | {stats['size_1']:>7} | {stats['size_2_3']:>8} | "
              f"{stats['size_4plus']:>7} | {stats['max_size']:>8}")

        if abs(dt - DUMP_THRESHOLD) < 1e-9:
            dump_events = events

    print("=" * 70)

    if dump_events is not None:
        print(f"\n📋 distance_threshold={DUMP_THRESHOLD} 的前 {TOP_N_CLUSTERS_TO_DUMP} 大群（供人工判讀）：")
        dump_top_clusters(dump_events, TOP_N_CLUSTERS_TO_DUMP)


if __name__ == "__main__":
    main()
