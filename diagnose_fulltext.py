"""
diagnose_fulltext.py — 從 news.db 隨機抽 10 篇有 full_text 的文章，
印出噪音診斷報告（頭尾各 500 字、連結數量、最長純連結行段落）。
"""

import re
import sqlite3

DB_PATH = "data/news.db"
SAMPLE_N = 10
HEAD_TAIL_CHARS = 500

# 純連結行的判斷 pattern
_MD_LINK_LINE   = re.compile(r'^\[.*\]\(.*\)$')
_BARE_URL_LINE  = re.compile(r'^https?://\S+$')

# 計數用 pattern
_MD_LINK_COUNT  = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
_IMG_LINK_COUNT = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')


def longest_link_streak(text: str) -> int:
    """回傳連續純連結行的最長段落長度（行數）。"""
    max_streak = 0
    current = 0
    for raw_line in text.split('\n'):
        line = raw_line.strip()
        if _MD_LINK_LINE.match(line) or _BARE_URL_LINE.match(line):
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def diagnose(row: tuple) -> None:
    title, url, full_text = row

    char_count   = len(full_text)
    md_links     = len(_MD_LINK_COUNT.findall(full_text))
    img_links    = len(_IMG_LINK_COUNT.findall(full_text))
    link_streak  = longest_link_streak(full_text)

    head = full_text[:HEAD_TAIL_CHARS]
    tail = full_text[-HEAD_TAIL_CHARS:] if char_count > HEAD_TAIL_CHARS else ""

    print(f"標題：{title}")
    print(f"URL：{url[:80]}")
    print(f"字元數：{char_count}")
    print(f"MD 連結數：{md_links} | 圖片連結數：{img_links} | 最長純連結段：{link_streak} 行")
    print()
    print("── HEAD ──")
    print(head)
    if tail:
        print()
        print("── TAIL ──")
        print(tail)


def main():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT title, url, full_text
        FROM articles
        WHERE full_text IS NOT NULL AND full_text != ''
        ORDER BY RANDOM()
        LIMIT ?
    """, (SAMPLE_N,)).fetchall()
    conn.close()

    if not rows:
        print("⚠️  資料庫中沒有含 full_text 的文章。")
        return

    print(f"共取得 {len(rows)} 篇文章\n")

    for i, row in enumerate(rows, 1):
        print(f"{'='*60}")
        print(f"=== 文章 {i} ===")
        print(f"{'='*60}")
        diagnose(row)
        print()


if __name__ == "__main__":
    main()
