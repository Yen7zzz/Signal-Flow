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
    """建立資料表（如果不存在）"""
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


def get_recent_articles(days: int = 7) -> list[dict]:
    """撈最近 N 天的所有文章"""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT category, title, summary, url, source, published
            FROM articles
            WHERE created_at >= datetime('now', ?)
            ORDER BY category, created_at DESC
        """, (f"-{days} days",)).fetchall()

    return [
        {
            "category": r[0], "title": r[1], "summary": r[2],
            "url": r[3], "source": r[4], "published": r[5]
        }
        for r in rows
    ]

if __name__ == "__main__":
    init_db()