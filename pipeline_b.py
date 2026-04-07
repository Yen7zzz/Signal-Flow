# ============================================================
# pipeline_b.py — 每週執行：撈新聞 → AI 整理 TOP5 → 寄 Email
#
# 兩階段摘要架構：
#   Stage 1：summarize_single()   — 逐篇摘要（sequential + rate limit）
#   Stage 2：summarize_category() — 跨文章選 TOP5 + 識別趨勢
# ============================================================

import json
import time
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from collections import defaultdict
from database import get_recent_articles
from config import (
    AI_PROVIDER,
    GROQ_API_KEY, GROQ_MODEL,
    OPENAI_API_KEY, OPENAI_MODEL,
    EMAIL_SENDER, EMAIL_PASSWORD,
    EMAIL_RECEIVERS, SMTP_HOST, SMTP_PORT, TOP_N
)

import os
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/pipeline_b.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

STAGE1_MAX_CHARS = 2000   # full_text 截斷長度（約 500-600 字）
STAGE1_SLEEP     = 2      # 兩次呼叫之間的最短間隔（Groq 30 RPM = 0.5 req/sec）
STAGE1_RETRIES   = 3      # 429 / RateLimitError 最多重試次數


# ── 不動的函式 ────────────────────────────────────────────────

def get_ai_client():
    """
    Groq 和 OpenAI 的 SDK 介面完全相同
    切換只需改 config.py 的 AI_PROVIDER
    """
    if AI_PROVIDER == "groq":
        from groq import Groq
        print(f"🤖 使用 Groq（{GROQ_MODEL}）— 免費測試模式")
        return Groq(api_key=GROQ_API_KEY), GROQ_MODEL
    else:
        from openai import OpenAI
        print(f"🤖 使用 OpenAI（{OPENAI_MODEL}）")
        return OpenAI(api_key=OPENAI_API_KEY), OPENAI_MODEL


def build_email_html(summaries_by_category: dict) -> str:
    date_range     = datetime.now().strftime("%Y 年 %m 月 %d 日")
    category_icons = {"Finance": "💰", "Technology": "🔬", "Politics": "🌏"}
    sections_html  = ""

    for category, result in summaries_by_category.items():
        articles = result.get("articles", []) if isinstance(result, dict) else result
        trend    = result.get("trend", "")    if isinstance(result, dict) else ""
        if not articles:
            continue
        icon       = category_icons.get(category, "📰")
        trend_html = f"""
            <div style="padding:12px;background:#f0f4f8;border-radius:4px;font-size:14px;color:#555;margin-bottom:20px;">
                📈 本週趨勢：{trend}
            </div>""" if trend else ""
        items_html = ""
        for item in articles:
            items_html += f"""
            <div style="margin-bottom:24px;padding:16px;background:#f9f9f9;border-left:4px solid #0066cc;border-radius:4px;">
                <div style="font-size:13px;color:#888;margin-bottom:4px;">#{item.get('rank','')} · {item.get('source','')}</div>
                <a href="{item.get('url','')}" style="font-size:17px;font-weight:bold;color:#0066cc;text-decoration:none;">
                    {item.get('title','')}
                </a>
                <p style="margin-top:8px;color:#333;line-height:1.6;font-size:15px;">
                    {item.get('key_points','')}
                </p>
                <a href="{item.get('url','')}" style="font-size:13px;color:#0066cc;">閱讀全文 →</a>
            </div>"""

        sections_html += f"""
        <div style="margin-bottom:40px;">
            <h2 style="font-size:20px;color:#222;border-bottom:2px solid #0066cc;padding-bottom:8px;">
                {icon} {category} TOP{TOP_N}
            </h2>
            {trend_html}
            {items_html}
        </div>"""

    return f"""
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="font-family:-apple-system,Arial,sans-serif;max-width:680px;margin:auto;padding:24px;color:#222;">
        <div style="text-align:center;padding:32px 0;border-bottom:1px solid #eee;">
            <h1 style="font-size:26px;color:#0066cc;margin:0;">📰 SignalFlow 每週新聞摘要</h1>
            <p style="color:#888;margin-top:8px;">{date_range} · 由 AI 為你整理重點</p>
        </div>
        <div style="padding-top:32px;">{sections_html}</div>
        <div style="text-align:center;padding:24px;border-top:1px solid #eee;color:#aaa;font-size:12px;">
            本郵件由 SignalFlow 自動生成
        </div>
    </body></html>
    """


def send_email(html_content: str):
    # EMAIL_RECEIVERS 是逗號分隔字串，拆成 list
    receivers = [r.strip() for r in EMAIL_RECEIVERS.split(",") if r.strip()]

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = f"📰 SignalFlow 週報 — {datetime.now().strftime('%Y/%m/%d')}"
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = ", ".join(receivers)
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    # 使用 SMTP + starttls（對應 port 587）
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, receivers, msg.as_string())

    print(f"📧 Email 已寄出 → {receivers}")
    logging.info(f"Email 寄出成功 → {receivers}")


# ── 新增 / 改寫的函式 ─────────────────────────────────────────

def _call_with_retry(client, model: str, messages: list[dict]) -> object:
    """
    API 呼叫包含 exponential backoff retry。
    429 / RateLimitError → 等 2^(n+1) 秒後重試，最多 STAGE1_RETRIES 次。
    其他例外直接 raise。
    """
    for attempt in range(STAGE1_RETRIES + 1):
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
            )
        except Exception as e:
            err = str(e).lower()
            is_rate_limit = "429" in err or "rate_limit" in err or "ratelimit" in err
            if is_rate_limit and attempt < STAGE1_RETRIES:
                wait = 2 ** (attempt + 1)  # 2 → 4 → 8 秒
                logging.warning(f"Rate limit，{wait}s 後重試（{attempt+1}/{STAGE1_RETRIES}）")
                print(f"      ⏳ Rate limit，{wait}s 後重試（{attempt+1}/{STAGE1_RETRIES}）...")
                time.sleep(wait)
            else:
                raise


def summarize_single(client, model: str, article: dict) -> dict | None:
    """
    Stage 1：單篇摘要
    優先用 full_text[:STAGE1_MAX_CHARS]，沒有則 fallback summary
    回傳 {title, url, source, category, key_points} 或 None（失敗時）
    """
    text = (article.get("full_text") or "")[:STAGE1_MAX_CHARS].strip()
    if not text:
        text = (article.get("summary") or "").strip()
    if not text:
        logging.warning(f"文章無可用內容，略過：{article.get('url', '')[:80]}")
        return None

    prompt = f"""你是專業新聞分析師。請分析以下新聞，提取關鍵資訊。

標題：{article['title']}
來源：{article.get('source', '')}
內容：
{text}

請用繁體中文，以 JSON 格式回傳分析結果：
{{
  "key_points": "3-5句結構化摘要，依序包含：①核心事件或決策 ②具體數據或當事方 ③潛在影響或後續發展"
}}

要求：每句以 ① ② ③ 編號開頭，只回傳 JSON，不要其他說明。"""

    try:
        response = _call_with_retry(client, model, [{"role": "user", "content": prompt}])
        raw      = response.choices[0].message.content.strip()
        raw      = raw.replace("```json", "").replace("```", "").strip()
        result   = json.loads(raw)
        return {
            "title":      article["title"],
            "url":        article["url"],
            "source":     article.get("source", ""),
            "category":   article["category"],
            "key_points": result.get("key_points", ""),
        }
    except Exception as e:
        logging.warning(f"Stage 1 摘要失敗 [{article.get('url', '')[:80]}]: {e}")
        return None


def run_stage1(client, model: str, articles: list[dict]) -> list[dict]:
    """
    逐篇呼叫 summarize_single()，每次呼叫後 sleep(STAGE1_SLEEP) 控制 rate limit。
    印出進度 [i/total]，回傳成功的摘要 list。
    """
    total   = len(articles)
    results = []

    print(f"\n📝 Stage 1：單篇摘要（{total} 篇，每次間隔 {STAGE1_SLEEP}s）")

    for i, article in enumerate(articles, 1):
        print(f"   [{i:3d}/{total}] {article['title'][:60]}")
        result = summarize_single(client, model, article)
        if result:
            results.append(result)
        else:
            print(f"          ❌ 略過")
        if i < total:            # 最後一篇不需要等
            time.sleep(STAGE1_SLEEP)

    success = len(results)
    print(f"\n   Stage 1 完成：成功 {success} / {total} 篇")
    logging.info(f"Stage 1 完成：成功 {success}，略過 {total - success}")
    return results


def summarize_category(client, model: str, category: str, summaries: list[dict]) -> list[dict]:
    """
    Stage 2：從 Stage 1 的摘要中選 TOP_N，說明為什麼重要，識別跨文章趨勢。
    """
    if not summaries:
        return []

    summary_list = "\n".join([
        f"{i+1}. 標題：{s['title']}\n   來源：{s['source']}\n   摘要：{s['key_points']}\n   連結：{s['url']}"
        for i, s in enumerate(summaries)
    ])

    prompt = f"""你是資深{category}新聞編輯。以下是本週各篇新聞的摘要分析：

{summary_list}

請完成兩件事：
1. 從中選出最重要的 {TOP_N} 篇，說明每篇的重要性（為什麼值得讀者關注）
2. 識別這些文章之間的共同趨勢或關聯（1-2句）

以 JSON 格式回傳：
{{
  "trend": "本週{category}領域的整體趨勢（1-2句繁體中文）",
  "articles": [
    {{
      "rank": 1,
      "title": "原始標題",
      "url": "原始連結",
      "source": "來源",
      "key_points": "為什麼重要 + 原始摘要重點（繁體中文，2-3句）"
    }}
  ]
}}

只回傳 JSON，不要其他說明。"""

    try:
        response = _call_with_retry(client, model, [{"role": "user", "content": prompt}])
        raw      = response.choices[0].message.content.strip()
        raw      = raw.replace("```json", "").replace("```", "").strip()
        result   = json.loads(raw)

        if isinstance(result, dict):
            trend    = result.get("trend", "")
            articles = result.get("articles", next(iter(result.values()), []))
        else:
            trend, articles = "", result

        if trend:
            print(f"   📈 趨勢：{trend}")
            logging.info(f"{category} 趨勢：{trend}")

        print(f"   ✅ AI 完成 {category} TOP{TOP_N} 整理")
        return {"trend": trend, "articles": articles}

    except Exception as e:
        logging.error(f"Stage 2 失敗 ({category}): {e}")
        print(f"   ❌ 失敗：{e}")
        return {"trend": "", "articles": []}


def run():
    print(f"\n{'='*50}")
    print(f"📊 Pipeline B 開始 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    client, model = get_ai_client()
    all_articles  = get_recent_articles(days=7)
    print(f"\n📦 共撈到 {len(all_articles)} 篇文章")

    if not all_articles:
        print("⚠️  無文章，Pipeline B 結束")
        logging.warning("Pipeline B：無文章可處理")
        return

    # Stage 1：逐篇摘要
    stage1_results = run_stage1(client, model, all_articles)

    if not stage1_results:
        print("⚠️  Stage 1 無成功結果，Pipeline B 結束")
        logging.warning("Pipeline B：Stage 1 無成功結果")
        return

    # 依分類分組
    by_category = defaultdict(list)
    for s in stage1_results:
        by_category[s["category"]].append(s)

    # Stage 2：跨文章選 TOP5 + 識別趨勢
    print(f"\n🏆 Stage 2：跨文章排名（{len(by_category)} 個分類）")
    summaries = {}
    for category, sums in by_category.items():
        print(f"\n   🔍 處理 {category}（{len(sums)} 篇摘要）...")
        summaries[category] = summarize_category(client, model, category, sums)

    html = build_email_html(summaries)
    send_email(html)

    total_top = sum(len(v["articles"]) for v in summaries.values())
    print(f"\n🎉 Pipeline B 完成！共選出 {total_top} 篇文章進入週報")
    logging.info(f"Pipeline B 完成，週報共 {total_top} 篇")


if __name__ == "__main__":
    run()
