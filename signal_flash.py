# ============================================================
# signal_flash.py — 每日 Pipeline A 後執行
# 用 Haiku 比對今日文章與上週週報趨勢，偵測方向性變化並推播 LINE
# ============================================================

import json
import logging
import os
import sqlite3

import anthropic
import requests

from config import ANTHROPIC_API_KEY, DB_PATH

logger = logging.getLogger(__name__)

CATEGORY_MAP = {
    "Finance":    "財經",
    "Technology": "科技",
    "Politics":   "政治",
}

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

HAIKU_MODEL = "claude-haiku-4-5-20251001"


def _get_articles(urls: list[str] | None) -> list[dict]:
    """
    撈文章（title + summary）。
    - urls 不為 None：依 MD5(url) hash 精確比對這批剛存入的文章。
    - urls 為 None（fallback）：撈最近 24 小時新入庫文章。
    """
    import hashlib
    with sqlite3.connect(DB_PATH) as conn:
        if urls is not None:
            hashes = [hashlib.md5(u.encode()).hexdigest() for u in urls]
            placeholders = ",".join("?" * len(hashes))
            rows = conn.execute(f"""
                SELECT category, title, summary
                FROM articles
                WHERE hash IN ({placeholders})
                ORDER BY category, id DESC
            """, hashes).fetchall()
        else:
            rows = conn.execute("""
                SELECT category, title, summary
                FROM articles
                WHERE created_at >= datetime('now', '-1 day')
                ORDER BY category, id DESC
            """).fetchall()
    return [{"category": r[0], "title": r[1], "summary": r[2] or ""} for r in rows]


def _get_last_trends() -> dict[str, str]:
    """回傳 {英文分類: trend 文字}，若無歷史資料則略過該分類。"""
    from database import get_last_weekly_digest
    trends = {}
    for eng_cat in CATEGORY_MAP:
        digest = get_last_weekly_digest(eng_cat)
        if digest and digest.get("trend"):
            trends[eng_cat] = digest["trend"]
    return trends


def _build_prompt(today_articles: list[dict], last_trends: dict[str, str]) -> str:
    lines = []
    lines.append("你是一位財經/科技/政治新聞分析師。")
    lines.append("以下是各分類上週週報的趨勢摘要，以及今日新收錄的文章標題清單。")
    lines.append("請判斷今日文章是否出現「相對上週趨勢的方向性變化」。")
    lines.append("")
    lines.append("【判斷標準】")
    lines.append("- 只有「方向性反轉」或「重大突發事件」才算 signal，日常延續不算。")
    lines.append("- 例：上週趨勢「美伊僵局油價飆升」，今日出現多篇美伊和談報導 → 算 signal。")
    lines.append("- 例：上週趨勢「Fed 暗示降息」，今日文章繼續討論降息預期 → 不算 signal。")
    lines.append("")

    for eng_cat, zh_cat in CATEGORY_MAP.items():
        if eng_cat not in last_trends:
            continue
        lines.append(f"【{zh_cat}】上週趨勢：{last_trends[eng_cat]}")
        cat_articles = [a for a in today_articles if a["category"] == eng_cat]
        if cat_articles:
            lines.append(f"今日文章（共 {len(cat_articles)} 篇）：")
            for a in cat_articles:
                lines.append(f"  - {a['title']}")
        else:
            lines.append("今日文章：（無）")
        lines.append("")

    lines.append("請以 JSON 格式回答，不要加任何說明文字，只輸出 JSON：")
    lines.append(json.dumps({
        "has_signal": True,
        "signals": [
            {
                "category": "財經（範例）",
                "change": "一句話描述方向性變化",
                "evidence": ["觸發判斷的文章標題1", "文章標題2"],
            }
        ],
    }, ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("以上為 JSON 格式示範，category 欄位的『（範例）』二字請移除。請依實際文章內容獨立判斷，不要照搬範例。")
    lines.append("若無任何 signal，回傳：{\"has_signal\": false, \"signals\": []}")
    lines.append("回傳語言：繁體中文。")

    return "\n".join(lines)


def _call_haiku(prompt: str) -> dict | None:
    """呼叫 Haiku，回傳解析後的 dict；失敗回傳 None。"""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # 去除可能的 markdown code fence
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except anthropic.APIError as e:
        logger.warning("Haiku API 失敗：%s", e)
        print(f"[WARNING] Haiku API 失敗：{e}")
        return None
    except json.JSONDecodeError as e:
        logger.warning("JSON 解析失敗：%s", e)
        print(f"[WARNING] JSON 解析失敗：{e}")
        return None


def _build_line_message(signals: list[dict], last_trends: dict[str, str]) -> str:
    zh_to_eng = {v: k for k, v in CATEGORY_MAP.items()}
    parts = ["⚡ SignalFlow 即時訊號\n"]
    for sig in signals:
        zh_cat = sig.get("category", "")
        eng_cat = zh_to_eng.get(zh_cat, "")
        prev_trend = last_trends.get(eng_cat, "（無歷史資料）")
        change = sig.get("change", "")
        evidence = sig.get("evidence", [])
        parts.append(f"【{zh_cat}】上週趨勢：{prev_trend}")
        parts.append(f"→ 轉變：{change}")
        if evidence:
            parts.append("相關報導：")
            for title in evidence:
                parts.append(f"• {title}")
        parts.append("")
    message = "\n".join(parts).rstrip()
    if len(message) > 4500:
        message = message[:4500] + "...（訊息過長已截斷）"
    return message


def _push_line(message: str) -> None:
    """透過 LINE Messaging API 推播訊息；失敗只 log，不中斷。"""
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.environ.get("LINE_USER_ID", "")
    if not token or not user_id:
        logger.warning("LINE 環境變數未設定（LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID），跳過推播。")
        print("[WARNING] LINE 環境變數未設定（LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID），跳過推播。")
        return
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}],
    }
    try:
        resp = requests.post(
            LINE_PUSH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            print("LINE 推播成功。")
        else:
            logger.warning("LINE 推播失敗：%s %s", resp.status_code, resp.text)
            print(f"[WARNING] LINE 推播失敗：{resp.status_code} {resp.text}")
    except requests.RequestException as e:
        logger.warning("LINE 推播例外：%s", e)
        print(f"[WARNING] LINE 推播例外：{e}")


def run_signal_flash(newly_saved_urls: list[str] | None = None) -> None:
    """
    Pipeline A 跑完後呼叫；偵測方向性訊號並推播 LINE。
    - newly_saved_urls 傳入時，精確比對這批剛存入的文章。
    - 不傳入時，fallback 撈最近 24 小時文章。
    """
    print("=== signal_flash 開始 ===")

    today_articles = _get_articles(newly_saved_urls)
    if len(today_articles) < 5:
        print(f"今日新文章 {len(today_articles)} 篇，樣本過少，靜默退出。")
        return

    print(f"今日新文章：{len(today_articles)} 篇")

    last_trends = _get_last_trends()
    if not last_trends:
        print("無任何分類的歷史趨勢資料，靜默退出。")
        return

    print(f"取得歷史趨勢分類：{list(last_trends.keys())}")

    prompt = _build_prompt(today_articles, last_trends)
    result = _call_haiku(prompt)
    if result is None:
        return

    if not result.get("has_signal"):
        print("今日無方向性訊號，靜默退出。")
        return

    signals = result.get("signals", [])
    if not signals:
        print("has_signal=true 但 signals 為空，靜默退出。")
        return

    print(f"偵測到 {len(signals)} 個訊號，準備推播 LINE。")
    message = _build_line_message(signals, last_trends)
    _push_line(message)
    print("=== signal_flash 完成 ===")


if __name__ == "__main__":
    run_signal_flash()
