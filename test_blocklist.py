# ============================================================
# test_blocklist.py — 一次性測試腳本：驗證 TITLE_BLOCKLIST 是否有誤殺
#
# 只讀 DB，不寫入任何資料。撈近 7 天所有文章標題，
# 套用 config.TITLE_BLOCKLIST / TITLE_BLOCKLIST_PATTERNS，
# 印出會被擋掉的標題清單供人工確認。
# ============================================================

import re

from config import TITLE_BLOCKLIST, TITLE_BLOCKLIST_PATTERNS
from database import get_recent_articles


def is_blocklisted_title(title: str) -> bool:
    title_lower = title.lower()
    if any(keyword in title_lower for keyword in TITLE_BLOCKLIST):
        return True
    if any(re.search(pattern, title_lower) for pattern in TITLE_BLOCKLIST_PATTERNS):
        return True
    return False


def main():
    articles = get_recent_articles(days=7)
    print(f"📦 近 7 天共 {len(articles)} 篇文章")

    blocked = [a for a in articles if is_blocklisted_title(a["title"])]

    print(f"\n🚫 會被黑名單擋掉的標題（共 {len(blocked)} 篇）：\n")
    for a in blocked:
        print(f"  [{a['category']}] {a['title']}")
        print(f"      來源：{a['source']}　URL：{a['url']}")

    print(f"\n總計：{len(blocked)} / {len(articles)} 篇會被擋掉")


if __name__ == "__main__":
    main()
