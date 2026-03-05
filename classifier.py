# ============================================================
# classifier.py — Transformer 語意分類器
#
# 為什麼比 Cosine 相似度好？
# Cosine：把「載具」永遠對應同一個向量（靜態）
# Transformer：看整句話的上下文再決定意思（動態）
#
# 使用 Zero-shot Classification：
# 不需要自己標記訓練資料，直接讓模型判斷
# 模型：facebook/bart-large-mnli（英文強）
#       MoritzLaurer/mDeBERTa-v3-base-mnli（多語言，中文好）
# ============================================================

from transformers import pipeline
import logging

logger = logging.getLogger(__name__)


class NewsClassifier:
    """
    用 Transformer Zero-shot Classification 判斷文章屬於哪個分類
    
    Zero-shot 的意思：
    你不用給任何訓練資料，直接問模型
    「這篇文章是財經、科技還是政治？」
    模型靠理解語意來回答，不是靠關鍵字比對
    """

    # 分類描述：描述越詳細，模型判斷越準
    # 這裡是關鍵：用「完整句子描述」比「單一關鍵字」準很多
    CATEGORY_DESCRIPTIONS = {
        "財經": "financial news about stock market, interest rates, inflation, economy, central bank, Fed, investment, corporate earnings, currency exchange",
        "科技": "technology news about AI, artificial intelligence, semiconductor, chips, software, hardware, tech companies, startups, cybersecurity",
        "政治": "political news about elections, government policy, international relations, diplomacy, war, conflict, United Nations, geopolitics",
    }

    def __init__(self, model_name: str = "cross-encoder/nli-MiniLM2-L6-H768"):
        """
        載入模型（第一次執行會自動下載，約 900MB）
        
        模型選擇：
        - MoritzLaurer/mDeBERTa-v3-base-mnli：多語言，中英文都好，推薦
        - facebook/bart-large-mnli：英文最強，但不支援中文
        - cross-encoder/nli-MiniLM2-L6-H768：輕量快速，準度稍低
        """
        print(f"🔄 載入 Transformer 模型：{model_name}")
        print("   （第一次執行需要下載模型，約 900MB，之後會快）")
        
        self.classifier = pipeline(
            "zero-shot-classification",
            model=model_name,
            device=-1,  # -1 = CPU，有 GPU 改成 0
        )
        self.labels = list(self.CATEGORY_DESCRIPTIONS.keys())
        self.label_descriptions = list(self.CATEGORY_DESCRIPTIONS.values())
        print("✅ 模型載入完成")

    def classify(self, text: str, threshold: float = 0.4) -> dict:
        """
        判斷文章屬於哪個分類，以及信心分數
        
        Args:
            text: 文章標題 + 摘要
            threshold: 信心分數門檻，低於此值視為「不相關」
            
        Returns:
            {
                "category": "財經",      # 最高分的分類
                "score": 0.87,           # 信心分數
                "is_relevant": True,     # 是否超過門檻
                "all_scores": {...}      # 各分類的分數
            }
        
        為什麼用 label_descriptions 而不直接用分類名稱？
        直接用「財經」→ 模型只看這兩個字
        用完整描述 → 模型理解「這個分類包含哪些概念」，判斷更準
        """
        result = self.classifier(
            text,
            candidate_labels=self.label_descriptions,
            multi_label=False,  # 每篇文章只屬於一個主分類
        )

        # 把描述對應回分類名稱
        desc_to_name = {v: k for k, v in self.CATEGORY_DESCRIPTIONS.items()}
        
        top_desc  = result["labels"][0]
        top_score = result["scores"][0]
        top_category = desc_to_name.get(top_desc, top_desc)

        all_scores = {
            desc_to_name.get(desc, desc): round(score, 3)
            for desc, score in zip(result["labels"], result["scores"])
        }

        return {
            "category":    top_category,
            "score":       round(top_score, 3),
            "is_relevant": top_score >= threshold,
            "all_scores":  all_scores,
        }

    def batch_classify(self, articles: list[dict], threshold: float = 0.4) -> list[dict]:
        """
        批次處理一批文章，回傳通過門檻的文章
        
        Args:
            articles: [{"title": ..., "summary": ..., "url": ...}, ...]
            threshold: 信心分數門檻
        """
        results = []
        for i, article in enumerate(articles):
            text = f"{article.get('title', '')}. {article.get('summary', '')}"
            classification = self.classify(text, threshold)
            
            if classification["is_relevant"]:
                article["category"]       = classification["category"]
                article["relevance_score"] = classification["score"]
                results.append(article)
                print(f"  ✅ [{classification['score']:.2f}] {article['title'][:50]}...")
            else:
                print(f"  ❌ [{classification['score']:.2f}] 過濾掉：{article['title'][:50]}...")

            # 每 10 篇顯示進度
            if (i + 1) % 10 == 0:
                print(f"  📊 進度：{i+1}/{len(articles)}")

        print(f"\n  📈 保留率：{len(results)}/{len(articles)} ({len(results)/len(articles)*100:.0f}%)")
        return results
