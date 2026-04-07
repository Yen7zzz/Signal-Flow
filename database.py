# ============================================================
# database.py — SQLite 資料庫初始化與操作
# ============================================================

import sqlite3
import hashlib
from config import DB_PATH
import os

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    """建立資料表（如果不存在），並執行向下相容 migration"""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                hash        TEXT UNIQUE,        -- 用來去重
                category    TEXT NOT NULL,
                title       TEXT NOT NULL,
                summary     TEXT,
                url         TEXT NOT NULL,
                source      TEXT,
                published   TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        # Migration：為舊資料庫加入 full_text 欄位
        # SQLite 不支援 ADD COLUMN IF NOT EXISTS，用 try/except 處理
        try:
            conn.execute("ALTER TABLE articles ADD COLUMN full_text TEXT")
        except sqlite3.OperationalError:
            pass  # 欄位已存在，略過
        conn.commit()
    print("✅ 資料庫初始化完成")


def article_exists(url: str) -> bool:
    """檢查文章是否已存在（去重）"""
    h = hashlib.md5(url.encode()).hexdigest()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM articles WHERE hash = ?", (h,)
        ).fetchone()
    return row is not None


def save_article(category: str, title: str, url: str,
                 summary: str = "", source: str = "", published: str = ""):
    """存入一篇文章"""
    h = hashlib.md5(url.encode()).hexdigest()
    with get_connection() as conn:
        try:
            conn.execute("""
                INSERT INTO articles (hash, category, title, summary, url, source, published)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (h, category, title, summary, url, source, published))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # 已存在，略過


def update_full_text(url: str, full_text: str) -> None:
    """更新指定文章的全文"""
    h = hashlib.md5(url.encode()).hexdigest()
    with get_connection() as conn:
        conn.execute(
            "UPDATE articles SET full_text = ? WHERE hash = ?",
            (full_text, h)
        )
        conn.commit()


def get_recent_articles(days: int = 7) -> list[dict]:
    """撈最近 N 天的所有文章"""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT category, title, summary, url, source, published, full_text
            FROM articles
            WHERE created_at >= datetime('now', ?)
            ORDER BY category, created_at DESC
        """, (f"-{days} days",)).fetchall()

    return [
        {
            "category": r[0], "title": r[1], "summary": r[2],
            "url": r[3], "source": r[4], "published": r[5],
            "full_text": r[6],   # nullable，舊資料為 None
        }
        for r in rows
    ]

if __name__ == "__main__":
    init_db()