# ============================================================
# scraper.py — 全文抓取模組
# 主要：trafilatura，fallback：newspaper3k
# ============================================================

import logging
import requests
import trafilatura
from newspaper import Article

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_full_text(url: str, timeout: int = 10) -> str | None:
    """
    抓取並回傳清理過的全文純文字。

    流程：requests 取得 HTML → trafilatura 解析 → newspaper3k fallback
    任何失敗皆 log warning 並回傳 None，不對外 raise。
    """
    # ── Step 1: 取得原始 HTML ──────────────────────────────────
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.warning(f"⚠️  HTTP 失敗 [{url[:80]}]: {e}")
        return None

    # ── Step 2: trafilatura 解析 ───────────────────────────────
    try:
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            no_fallback=False,     # 允許 trafilatura 內部 fallback
        )
        if text and text.strip():
            return text.strip()
    except Exception as e:
        logger.warning(f"⚠️  trafilatura 解析失敗 [{url[:80]}]: {e}")

    # ── Step 3: newspaper3k fallback ──────────────────────────
    try:
        article = Article(url, language="en")
        article.set_html(html)
        article.parse()
        text = article.text
        if text and text.strip():
            return text.strip()
    except Exception as e:
        logger.warning(f"⚠️  newspaper3k fallback 失敗 [{url[:80]}]: {e}")

    logger.warning(f"⚠️  無法擷取全文，兩種方法皆失敗 [{url[:80]}]")
    return None
