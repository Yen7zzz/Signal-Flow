# ============================================================
# cleanup_fulltext.py — 清除超過 N 天前文章的 full_text 內容
#
# full_text 只在 pipeline_b.py 被拿來做 len() 判斷（產生 ✅/⚠️ 標記），
# 聚類與 digest 內容皆不使用其文字內容，且 pipeline_b 只撈最近 7 天資料，
# 因此較舊的 full_text 已無讀取需求，可清空以控制 news.db 體積。
#
# 用法：
#   python cleanup_fulltext.py --days 30 --dry-run   # 只統計，不修改
#   python cleanup_fulltext.py --days 30             # 實際清除 + VACUUM
# ============================================================

import argparse
import os
import sqlite3
import sys

from config import DB_PATH, FULLTEXT_RETENTION_DAYS

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def get_file_size(path: str) -> int:
    return os.path.getsize(path)


def clear_old_fulltext(days: int, db_path: str = DB_PATH) -> int:
    """
    清空超過 N 天前的 full_text（只做 UPDATE，不含 VACUUM）。
    供每日 pipeline 與本檔案的 CLI 共用，回傳被清空的筆數。
    """
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute(
            """
            UPDATE articles
            SET full_text = NULL
            WHERE created_at < datetime('now', ?)
              AND full_text IS NOT NULL
            """,
            (f"-{days} days",),
        )
        affected = cur.rowcount
        con.commit()
        return affected
    finally:
        con.close()


def dry_run_stats(days: int) -> None:
    uri = f"file:{DB_PATH}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    cur = con.cursor()

    cur.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(LENGTH(full_text)), 0)
        FROM articles
        WHERE created_at < datetime('now', ?)
          AND full_text IS NOT NULL
        """,
        (f"-{days} days",),
    )
    affected_rows, total_chars = cur.fetchone()
    con.close()

    approx_bytes = len(("a" * total_chars).encode("utf-8")) if total_chars else 0
    # 上面用 ascii 估算下限；用資料庫實際文字重算 UTF-8 位元組數更準確，另外查一次
    con = sqlite3.connect(uri, uri=True)
    cur = con.cursor()
    cur.execute(
        """
        SELECT COALESCE(SUM(LENGTH(CAST(full_text AS BLOB))), 0)
        FROM articles
        WHERE created_at < datetime('now', ?)
          AND full_text IS NOT NULL
        """,
        (f"-{days} days",),
    )
    total_bytes = cur.fetchone()[0]
    con.close()

    file_size = get_file_size(DB_PATH)

    print(f"\n{'='*50}")
    print(f"🔍 Dry-run 統計（--days {days}）")
    print(f"{'='*50}")
    print(f"目前檔案大小：{file_size:,} bytes（{file_size/1024/1024:.2f} MB）")
    print(f"會被影響的筆數：{affected_rows:,}")
    print(f"full_text 總字元數：{total_chars:,}")
    print(f"full_text 總位元組數（UTF-8）：{total_bytes:,}（{total_bytes/1024/1024:.2f} MB）")
    print("不會做任何修改（dry-run 模式）")
    print(f"{'='*50}\n")


def do_cleanup(days: int) -> None:
    confirm = input(
        f"⚠️  即將清除 {days} 天前的 full_text 並執行 VACUUM，此操作不可逆。"
        f"輸入 yes 以繼續："
    )
    if confirm.strip().lower() != "yes":
        print("已取消，未做任何修改。")
        return

    size_before = get_file_size(DB_PATH)
    print(f"執行前檔案大小：{size_before:,} bytes（{size_before/1024/1024:.2f} MB）")

    affected = clear_old_fulltext(days)
    print(f"已清除 {affected:,} 筆 full_text，執行 VACUUM 中...")

    con = sqlite3.connect(DB_PATH)
    con.execute("VACUUM")
    con.close()

    size_after = get_file_size(DB_PATH)
    print(f"執行後檔案大小：{size_after:,} bytes（{size_after/1024/1024:.2f} MB）")
    print(f"回收空間：{size_before - size_after:,} bytes（{(size_before - size_after)/1024/1024:.2f} MB）")


def main():
    parser = argparse.ArgumentParser(description="清除歷史 full_text 以控制 news.db 體積")
    parser.add_argument(
        "--days", type=int, default=FULLTEXT_RETENTION_DAYS,
        help=f"清除幾天前的 full_text（預設 {FULLTEXT_RETENTION_DAYS}）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只統計，不修改任何資料")
    args = parser.parse_args()

    if args.dry_run:
        dry_run_stats(args.days)
    else:
        do_cleanup(args.days)


if __name__ == "__main__":
    main()
