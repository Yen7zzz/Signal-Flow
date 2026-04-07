# ============================================================
# test_scraper.py — 手動驗證 fetch_full_text()
# 執行：python test_scraper.py
# ============================================================

from scraper import fetch_full_text

FEED_URL    = "https://hnrss.org/frontpage"
FEED_LIMIT  = 2
FAKE_URL    = "https://this-domain-does-not-exist-signalflow-test.xyz/article"
PREVIEW_LEN = 200
SEP         = "-" * 60


def build_test_cases() -> list[dict]:
    """從 HN frontpage RSS 動態取前 N 篇真實 URL"""
    import feedparser
    print(f"📡 從 RSS 取測試 URL：{FEED_URL}")
    feed = feedparser.parse(FEED_URL)
    cases = []
    for entry in feed.entries[:FEED_LIMIT]:
        cases.append({
            "label": f"HN 即時文章：{entry.get('title', '')[:50]}",
            "url":   entry.get("link", ""),
        })
    cases.append({
        "label": "假 URL（預期失敗）",
        "url":   FAKE_URL,
    })
    return cases


def run():
    print(f"\n{'='*60}")
    print("  fetch_full_text() 驗證腳本")
    print(f"{'='*60}\n")

    test_cases = build_test_cases()

    for case in test_cases:
        label = case["label"]
        url   = case["url"]
        print(f"【{label}】")
        print(f"URL: {url}")

        text = fetch_full_text(url, timeout=15)

        if text:
            print(f"結果:   ✅ 成功")
            print(f"長度:   {len(text)} 字元")
            preview = text[:PREVIEW_LEN].replace("\n", " ")
            print(f"預覽:   {preview}...")
        else:
            print(f"結果:   ❌ 失敗（回傳 None）")

        print(SEP)


if __name__ == "__main__":
    run()
