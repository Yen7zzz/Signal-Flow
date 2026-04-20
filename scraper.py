# ============================================================
# scraper.py — 全文抓取模組
# 主要：trafilatura，fallback：newspaper3k
# ============================================================

import logging
import re
import requests
import trafilatura
from newspaper import Article

logger = logging.getLogger(__name__)

_TAIL_CUT_RE = re.compile(
    r'related articles|related stories|recommended|stay connected|'
    r'get the latest|subscribe|sign up for|newsletter|more from|'
    r'popular stories|trending|you may also like|read next|don\'t miss',
    re.IGNORECASE,
)
_MULTI_BLANK_RE = re.compile(r'\n{3,}')
_MIN_LENGTH = 200


def clean_full_text(text: str) -> str | None:
    """
    清理 trafilatura / newspaper3k 回傳的全文：
    1. TAIL CTA 截斷：遇到 CTA 關鍵字行，從該行起整段截掉
    2. 連續空行壓縮：3+ 個換行 → 2 個換行
    3. 最低長度門檻：清理後 < 200 字 → return None
    """
    lines = text.split('\n')
    cutoff = len(lines)
    for i, line in enumerate(lines):
        if _TAIL_CUT_RE.search(line):
            cutoff = i
            break
    cleaned = '\n'.join(lines[:cutoff])
    cleaned = _MULTI_BLANK_RE.sub('\n\n', cleaned).strip()
    if len(cleaned) < _MIN_LENGTH:
        return None
    return cleaned


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
            return clean_full_text(text)
    except Exception as e:
        logger.warning(f"⚠️  trafilatura 解析失敗 [{url[:80]}]: {e}")

    # ── Step 3: newspaper3k fallback ──────────────────────────
    try:
        article = Article(url, language="en")
        article.set_html(html)
        article.parse()
        text = article.text
        if text and text.strip():
            return clean_full_text(text)
    except Exception as e:
        logger.warning(f"⚠️  newspaper3k fallback 失敗 [{url[:80]}]: {e}")

    logger.warning(f"⚠️  無法擷取全文，兩種方法皆失敗 [{url[:80]}]")
    return None
