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
        topics: dict[str, list[str]],
        threshold: float = 0.4,
    ) -> dict[str, list[dict]]:
        """
        偵測每個追蹤主題在本週摘要中的命中文章。
        每個主題提供英文別名 list，取所有別名中的最高 similarity 作為匹配分數。

        Args:
            summaries:  Stage 1 結果，每個 dict 含 title, key_points, url, source, category
            topics:     {中文顯示名: [英文別名, ...]}，例如 {"AI 晶片": ["AI chip", "GPU", ...]}
            threshold:  cosine similarity 門檻，超過視為命中

        Returns:
            {"AI 晶片": [matched_article_dicts, ...], "Fed 利率": [...], ...}
        """
        if not topics or not summaries:
            return {}

        # ── 編碼文章（一次） ──────────────────────────────────────
        article_texts = [
            f"{art.get('title', '')}. {art.get('key_points') or art.get('summary') or ''}"
            for art in summaries
        ]
        article_embeddings = self.model.encode(article_texts, show_progress_bar=False)

        # ── 把所有主題的別名 flatten，一次編碼 ───────────────────
        topic_names: list[str] = list(topics.keys())
        # alias_groups[i] = 第 i 個主題的別名 list（含中文 key 本身）
        alias_groups: list[list[str]] = [
            [name] + aliases for name, aliases in topics.items()
        ]
        # flat list，並記錄每個 alias 屬於哪個主題 index
        flat_aliases: list[str] = []
        alias_topic_idx: list[int] = []
        for topic_idx, aliases in enumerate(alias_groups):
            for alias in aliases:
                flat_aliases.append(alias)
                alias_topic_idx.append(topic_idx)

        alias_embeddings = self.model.encode(flat_aliases, show_progress_bar=False)

        # ── 計算 similarity，shape: (n_articles, n_flat_aliases) ──
        sim_flat = cosine_similarity(article_embeddings, alias_embeddings)

        # ── 對每個主題取其所有別名的最大 similarity ───────────────
        n_topics   = len(topic_names)
        n_articles = len(summaries)
        # max_sim[i, j] = 第 i 篇文章對第 j 個主題的最高別名 similarity
        max_sim = np.full((n_articles, n_topics), -1.0)
        for col, t_idx in enumerate(alias_topic_idx):
            max_sim[:, t_idx] = np.maximum(max_sim[:, t_idx], sim_flat[:, col])

        # ── 按門檻篩選命中 ────────────────────────────────────────
        results: dict[str, list[dict]] = {}
        for j, topic in enumerate(topic_names):
            matched = [
                summaries[i]
                for i in range(n_articles)
                if max_sim[i, j] > threshold
            ]
            results[topic] = matched
            print(f"  📡 {topic}：命中 {len(matched)} 篇")

        return results
