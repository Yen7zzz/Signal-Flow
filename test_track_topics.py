# ============================================================
# test_track_topics.py — 驗證 track_topics() 雙語別名匹配
#
# 不呼叫任何 LLM API，只測試本地 SentenceTransformer 匹配邏輯。
# ============================================================

from clusterer import NewsClusterer
from config import TRACKED_TOPICS, TOPIC_SIMILARITY_THRESHOLD

# ── 假文章：模擬 Stage 1 輸出格式 ────────────────────────────
FAKE_ARTICLES = [
    # Fed / interest rate（2 篇）
    {
        "title":      "Federal Reserve holds rates steady amid inflation concerns",
        "key_points": "①聯準會在最新會議中維持利率不變，暫不啟動降息。②通膨數據仍高於 2% 目標，FOMC 委員分歧加大。③市場預期今年僅剩一次降息窗口，美元指數走強。",
        "url":        "https://example.com/fed-rates-steady",
        "source":     "Reuters",
        "category":   "Finance",
    },
    {
        "title":      "FOMC minutes signal caution on rate cuts as labor market stays tight",
        "key_points": "①聯準會會議紀錄顯示，多數委員對過早降息保持謹慎。②就業市場依然強勁，非農就業新增超預期。③貨幣政策維持限制性立場，下次會議將評估最新 CPI 數據。",
        "url":        "https://example.com/fomc-minutes-caution",
        "source":     "Bloomberg",
        "category":   "Finance",
    },

    # TSMC / 台積電（2 篇）
    {
        "title":      "TSMC reports record Q1 revenue driven by AI chip demand",
        "key_points": "①台積電公布第一季營收創歷史新高，年增 42%。②AI 加速器與先進製程需求強勁，3nm 產能持續滿載。③管理層上調全年資本支出指引至 380 億美元。",
        "url":        "https://example.com/tsmc-q1-revenue",
        "source":     "CNBC",
        "category":   "Technology",
    },
    {
        "title":      "Taiwan Semiconductor expands Arizona fab capacity ahead of schedule",
        "key_points": "①台積電亞利桑那廠擴產進度超前，預計提前量產 2nm 製程。②美國政府補貼到位，廠區第二期工程正式動工。③此舉強化台積電在地緣政治風險下的產能多元布局。",
        "url":        "https://example.com/tsmc-arizona-expansion",
        "source":     "Financial Times",
        "category":   "Technology",
    },

    # AI chip / GPU（1 篇）
    {
        "title":      "Nvidia unveils next-gen GPU architecture for AI training workloads",
        "key_points": "①Nvidia 發表新一代 GPU 架構，AI 訓練效能較上代提升 3 倍。②新晶片採用台積電 3nm 製程，單卡功耗控制在 700W 以內。③預計 2025 年底量產，主要客戶包含各大雲端服務商。",
        "url":        "https://example.com/nvidia-next-gen-gpu",
        "source":     "The Verge",
        "category":   "Technology",
    },

    # 雜訊（2 篇）
    {
        "title":      "Manchester United wins Premier League title in dramatic final",
        "key_points": "①曼聯以 3:2 擊敗阿森納，時隔十年重奪英超冠軍。②主力射手賽季共打進 28 球，榮獲金靴獎。③球隊將代表英格蘭出征下賽季歐冠聯賽。",
        "url":        "https://example.com/man-utd-premier-league",
        "source":     "BBC Sport",
        "category":   "Sports",
    },
    {
        "title":      "Severe thunderstorms expected across the US Midwest this weekend",
        "key_points": "①美國中西部本週末將迎來強烈雷雨系統，多州發布警報。②預測降雨量超過 150mm，部分地區有龍捲風風險。③當局建議居民避免外出，提前準備緊急物資。",
        "url":        "https://example.com/midwest-thunderstorms",
        "source":     "Weather.com",
        "category":   "General",
    },
]

NOISE_URLS = {
    "https://example.com/man-utd-premier-league",
    "https://example.com/midwest-thunderstorms",
}


def main():
    print("=" * 55)
    print("  test_track_topics.py — 雙語別名匹配驗證")
    print("=" * 55)
    print(f"\n追蹤主題：{list(TRACKED_TOPICS.keys())}")
    print(f"相似度門檻：{TOPIC_SIMILARITY_THRESHOLD}\n")

    clusterer = NewsClusterer()

    topic_hits = clusterer.track_topics(
        FAKE_ARTICLES,
        TRACKED_TOPICS,
        TOPIC_SIMILARITY_THRESHOLD,
    )

    print()
    all_matched_urls: set[str] = set()

    for topic, matched in topic_hits.items():
        print(f"【{topic}】命中 {len(matched)} 篇")
        for art in matched:
            print(f"    • {art['title']}")
            all_matched_urls.add(art["url"])
        print()

    # ── Assertions ──────────────────────────────────────────
    assert len(topic_hits.get("AI 晶片", [])) >= 1, \
        f"❌ 'AI 晶片' 應命中 >= 1 篇，實際 {len(topic_hits.get('AI 晶片', []))}"

    assert len(topic_hits.get("Fed 利率", [])) >= 1, \
        f"❌ 'Fed 利率' 應命中 >= 1 篇，實際 {len(topic_hits.get('Fed 利率', []))}"

    assert len(topic_hits.get("台積電", [])) >= 1, \
        f"❌ '台積電' 應命中 >= 1 篇，實際 {len(topic_hits.get('台積電', []))}"

    for topic, matched in topic_hits.items():
        for art in matched:
            assert art["url"] not in NOISE_URLS, \
                f"❌ 雜訊文章不應出現在 '{topic}' 命中結果：{art['title']}"

    print("✅ 全部通過")


if __name__ == "__main__":
    main()
