# ============================================================
# pipeline_b.py — 每週執行：撈新聞 → AI 整理 TOP5 → 寄 Email
# 支援 Groq（免費測試）和 OpenAI（正式使用）
# 切換方式：改 config.py 的 AI_PROVIDER 就好
# ============================================================

import json
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
    EMAIL_RECEIVERS, SMTP_HOST, SMTP_PORT, TOP_N  # ← 改成複數
)

import os
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/pipeline_b.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


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


def summarize_category(client, model: str, category: str, articles: list[dict]) -> list[dict]:
    if not articles:
        return []

    article_list = "\n".join([
        f"{i+1}. 標題：{a['title']}\n   來源：{a['source']}\n   摘要：{a['summary'][:200]}\n   連結：{a['url']}"
        for i, a in enumerate(articles[:50])
    ])

    prompt = f"""你是一位專業的新聞編輯，專門整理{category}類新聞。

以下是本週收集到的{category}新聞清單：

{article_list}

請從中挑選最重要、最有價值的 {TOP_N} 篇新聞，並針對每篇：
1. 用 2-3 句繁體中文說明重點（為什麼重要、影響是什麼）
2. 保留原始連結和來源

以 JSON 格式回傳：
{{
  "articles": [
    {{
      "rank": 1,
      "title": "原始標題",
      "url": "原始連結",
      "source": "來源",
      "key_points": "重點摘要（繁體中文，2-3句）"
    }}
  ]
}}

只回傳 JSON，不要其他說明。"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        raw    = response.choices[0].message.content
        raw    = raw.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)

        if isinstance(result, dict):
            result = result.get("articles", next(iter(result.values()), []))

        print(f"   ✅ AI 完成 {category} TOP{TOP_N} 整理")
        return result

    except Exception as e:
        logging.error(f"AI 摘要失敗 ({category}): {e}")
        print(f"   ❌ 失敗：{e}")
        return []


def build_email_html(summaries_by_category: dict) -> str:
    date_range     = datetime.now().strftime("%Y 年 %m 月 %d 日")
    category_icons = {"財經": "💰", "科技": "🔬", "政治": "🌏"}
    sections_html  = ""

    for category, articles in summaries_by_category.items():
        if not articles:
            continue
        icon       = category_icons.get(category, "📰")
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
                {icon} {category}新聞 TOP{TOP_N}
            </h2>
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
    # EMAIL_RECEIVERS 支援多個收件人，用逗號分隔
    receivers = [r.strip() for r in EMAIL_RECEIVERS.split(",")]

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = f"📰 SignalFlow 週報 — {datetime.now().strftime('%Y/%m/%d')}"
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = ", ".join(receivers)
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, receivers, msg.as_string())

    print(f"📧 Email 已寄出 → {receivers}")
    logging.info(f"Email 寄出成功 → {receivers}")


def run():
    print(f"\n{'='*50}")
    print(f"📊 Pipeline B 開始 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    client, model = get_ai_client()
    all_articles  = get_recent_articles(days=7)
    print(f"\n📦 共撈到 {len(all_articles)} 篇文章")

    by_category = defaultdict(list)
    for article in all_articles:
        by_category[article["category"]].append(article)

    summaries = {}
    for category, articles in by_category.items():
        print(f"\n🔍 處理 {category}（{len(articles)} 篇）...")
        summaries[category] = summarize_category(client, model, category, articles)

    html = build_email_html(summaries)
    send_email(html)  # ← 取消註解，實際寄信
    print(f"\n🎉 Pipeline B 完成！")


if __name__ == "__main__":
    run()