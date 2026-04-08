# ============================================================
# clusterer.py — 主題聚類模組
#
# 把同主題的新聞合併成「事件」
#
# 流程：
# 1. 用 SentenceTransformer 把文章標題 + 重點編碼成向量
# 2. AgglomerativeClustering（層次聚類）依 cosine 距離分群
# 3. 每群選離 centroid 最近的文章為代表，其餘為相關報導
# 4. 按群組大小降序排列（報導密度高的事件排前面）
# ============================================================

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_similarity


class NewsClusterer:
    """
    用語意向量聚類，把報導同一事件的文章合併

    為什麼用 AgglomerativeClustering？
    - 不需要預先指定群數（n_clusters=None）
    - 用 distance_threshold 控制合併鬆緊度，直覺易調
    - cosine 距離適合文字向量（長度無關，只看方向）
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        載入 SentenceTransformer 模型（第一次執行會自動下載，約 90MB）

        模型選擇：
        - all-MiniLM-L6-v2：輕量快速，英文效果佳，推薦
        - paraphrase-multilingual-MiniLM-L12-v2：多語言，中英混合適用
        """
        print(f"🔄 載入 SentenceTransformer 模型：{model_name}")
        print("   （第一次執行需要下載模型，之後會快）")
        self.model = SentenceTransformer(model_name)
        print("✅ 模型載入完成")

    def cluster_articles(
        self,
        summaries: list[dict],
        distance_threshold: float = 0.35,
    ) -> list[dict]:
        """
        對 Stage 1 摘要結果做主題聚類，回傳事件列表

        Args:
            summaries: Stage 1 結果，每個 dict 包含
                       title, key_points, url, source, category
            distance_threshold: 聚類距離門檻（越小 → 群越細；越大 → 群越寬）

        Returns:
            list[dict]，每個 dict：
            {
                "representative": article_dict,   # 最具代表性的文章
                "related":        [article_dict, ...],  # 同群其餘文章
                "cluster_size":   int,            # 群內文章總數
            }
            按 cluster_size 降序排列
        """
        # ── 邊界條件：0 或 1 篇不需聚類 ──────────────────────────
        if len(summaries) <= 1:
            events = [
                {
                    "representative": summaries[0] if summaries else {},
                    "related": [],
                    "cluster_size": len(summaries),
                }
            ]
            print(f"  📊 {len(summaries)} 篇 → {len(events)} 個事件")
            return events

        # ── 編碼 ─────────────────────────────────────────────────
        texts = [
            f"{art.get('title', '')}. {art.get('key_points') or art.get('summary') or ''}"
            for art in summaries
        ]
        embeddings = self.model.encode(texts, show_progress_bar=False)

        # ── 聚類 ─────────────────────────────────────────────────
        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=distance_threshold,
            metric="cosine",
            linkage="average",
        )
        labels = clustering.fit_predict(embeddings)

        # ── 組裝事件 ─────────────────────────────────────────────
        cluster_ids = sorted(set(labels))
        events = []

        for cid in cluster_ids:
            indices = [i for i, lbl in enumerate(labels) if lbl == cid]
            cluster_embeddings = embeddings[indices]

            # centroid：群內所有向量的平均
            centroid = cluster_embeddings.mean(axis=0, keepdims=True)

            # 選離 centroid cosine similarity 最高的文章為代表
            sims = cosine_similarity(cluster_embeddings, centroid).flatten()
            rep_pos = int(np.argmax(sims))

            representative = summaries[indices[rep_pos]]
            related = [summaries[indices[i]] for i in range(len(indices)) if i != rep_pos]

            events.append(
                {
                    "representative": representative,
                    "related": related,
                    "cluster_size": len(indices),
                }
            )

        # 報導密度高的事件排前面
        events.sort(key=lambda e: e["cluster_size"], reverse=True)

        print(f"  📊 {len(summaries)} 篇 → {len(events)} 個事件")
        return events

    def track_topics(
        self,
        summaries: list[dict],
        topics: list[str],
        threshold: float = 0.4,
    ) -> dict[str, list[dict]]:
        """
        偵測每個追蹤主題在本週摘要中的命中文章。

        Args:
            summaries:  Stage 1 結果，每個 dict 含 title, key_points, url, source, category
            topics:     追蹤主題字串列表，例如 ["AI 晶片", "Fed 利率"]
            threshold:  cosine similarity 門檻，超過視為命中

        Returns:
            {"AI 晶片": [matched_article_dicts, ...], "Fed 利率": [...], ...}
        """
        if not topics:
            return {}

        topic_embeddings   = self.model.encode(topics, show_progress_bar=False)
        article_texts      = [
            f"{art.get('title', '')}. {art.get('key_points') or art.get('summary') or ''}"
            for art in summaries
        ]
        article_embeddings = self.model.encode(article_texts, show_progress_bar=False)

        # shape: (n_articles, n_topics)
        sim_matrix = cosine_similarity(article_embeddings, topic_embeddings)

        results: dict[str, list[dict]] = {}
        for j, topic in enumerate(topics):
            matched = [
                summaries[i]
                for i in range(len(summaries))
                if sim_matrix[i, j] > threshold
            ]
            results[topic] = matched
            print(f"  📡 {topic}：命中 {len(matched)} 篇")

        return results
