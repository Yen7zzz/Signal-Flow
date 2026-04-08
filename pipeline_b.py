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
from clusterer import NewsClusterer
from database import (
    init_db, get_recent_articles, save_weekly_digest, get_last_weekly_digest,
    save_topic_signal, get_last_topic_signal,
)
from config import (
    STAGE1_PROVIDER, STAGE1_MODEL,
    STAGE2_PROVIDER, STAGE2_MODEL, STAGE2_THINKING,
    GROQ_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY,
    EMAIL_SENDER, EMAIL_PASSWORD,
    EMAIL_RECEIVERS, SMTP_HOST, SMTP_PORT, TOP_N,
    TRACKED_TOPICS, TOPIC_SIMILARITY_THRESHOLD,
)

import os
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/pipeline_b.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

STAGE1_MAX_CHARS = 2000   # full_text 截斷長度（約 500-600 字）
STAGE1_SLEEP     = 2      # 兩次呼叫之間的最短間隔
STAGE1_RETRIES   = 3      # 429 / RateLimitError 最多重試次數


# ── 不動的函式 ────────────────────────────────────────────────

def get_ai_client(provider: str, model: str):
    """
    依 provider 建立對應的 API client，回傳 (client, model)。
    支援：groq / openai / gemini / anthropic
    """
    if provider == "groq":
        from groq import Groq
        print(f"🤖 Stage client：Groq（{model}）")
        return Groq(api_key=GROQ_API_KEY), model
    elif provider == "gemini":
        from openai import OpenAI
        print(f"🤖 Stage client：Gemini（{model}）")
        return OpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=GEMINI_API_KEY,
        ), model
    elif provider == "anthropic":
        import anthropic
        print(f"🤖 Stage client：Anthropic（{model}）")
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY), model
    else:  # openai（預設）
        from openai import OpenAI
        print(f"🤖 Stage client：OpenAI（{model}）")
        return OpenAI(api_key=OPENAI_API_KEY), model


def build_email_html(summaries_by_category: dict, topic_signals: dict | None = None) -> str:
    date_range     = datetime.now().strftime("%Y 年 %m 月 %d 日")
    category_icons = {"Finance": "💰", "Technology": "🔬", "Politics": "🌏"}
    sections_html  = ""

    for category, result in summaries_by_category.items():
        articles   = result.get("articles", [])   if isinstance(result, dict) else result
        trend      = result.get("trend", "")      if isinstance(result, dict) else ""
        cross_week = result.get("cross_week")     if isinstance(result, dict) else None
        if not articles:
            continue
        icon       = category_icons.get(category, "📰")
        trend_html = f"""
            <div style="padding:12px;background:#f0f4f8;border-radius:4px;font-size:14px;color:#555;margin-bottom:20px;">
                📈 本週趨勢：{trend}
            </div>""" if trend else ""
        cross_week_html = ""
        if cross_week:
            continuing = "、".join(cross_week.get("continuing", []))
            emerging   = "、".join(cross_week.get("emerging", []))
            parts      = ""
            if continuing:
                parts += f"🔄 延續議題：{continuing}<br>"
            if emerging:
                parts += f"🆕 新興議題：{emerging}"
            if parts:
                cross_week_html = f"""
            <div style="padding:12px;background:#fff8e1;border-radius:4px;font-size:14px;color:#555;margin-bottom:20px;">
                {parts}
            </div>"""
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
            {cross_week_html}
            {items_html}
        </div>"""

    # ── 訊號追蹤區塊 ─────────────────────────────────────────────
    signals_html = ""
    if topic_signals:
        max_count = max((v["current"] for v in topic_signals.values()), default=1) or 1
        rows_html = ""
        for topic, sig in topic_signals.items():
            current  = sig["current"]
            previous = sig["previous"]
            trend    = sig["trend"]
            bar_pct  = int(current / max_count * 100)
            if previous is None:
                prev_text = "首次追蹤"
            else:
                prev_text = f"上週 {previous} 篇 {trend}"
            rows_html += f"""
            <div style="display:flex;align-items:center;margin-bottom:12px;gap:12px;">
                <div style="width:80px;font-size:14px;color:#333;flex-shrink:0;">{topic}</div>
                <div style="flex:1;background:#e8eef4;border-radius:3px;height:20px;">
                    <div style="background:#0066cc;height:20px;border-radius:3px;width:{bar_pct}%;"></div>
                </div>
                <div style="width:160px;font-size:13px;color:#555;flex-shrink:0;">
                    {current} 篇（{prev_text}）
                </div>
            </div>"""
        signals_html = f"""
        <div style="margin-bottom:40px;">
            <h2 style="font-size:20px;color:#222;border-bottom:2px solid #0066cc;padding-bottom:8px;">
                📡 訊號追蹤
            </h2>
            {rows_html}
        </div>"""

    return f"""
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="font-family:-apple-system,Arial,sans-serif;max-width:680px;margin:auto;padding:24px;color:#222;">
        <div style="text-align:center;padding:32px 0;border-bottom:1px solid #eee;">
            <h1 style="font-size:26px;color:#0066cc;margin:0;">📰 SignalFlow 每週新聞摘要</h1>
            <p style="color:#888;margin-top:8px;">{date_range} · 由 AI 為你整理重點</p>
        </div>
        <div style="padding-top:32px;">{sections_html}{signals_html}</div>
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

class _AnthropicResponseWrapper:
    """模擬 OpenAI response.choices[0].message.content 介面，供 Anthropic SDK 回傳使用。"""
    def __init__(self, text: str):
        self.choices = [type("C", (), {"message": type("M", (), {"content": text})()})()]


def _call_with_retry(client, model: str, messages: list[dict],
                     provider: str = "openai", thinking: bool = False) -> object:
    """
    API 呼叫包含 exponential backoff retry。
    429 / RateLimitError → 等 2^(n+1) 秒後重試，最多 STAGE1_RETRIES 次。
    其他例外直接 raise。
    provider="anthropic" 時使用 client.messages.create() 並包裝成統一介面。
    thinking=True 時（僅 Gemini）加入 generationConfig.thinking_config。
    """
    extra_kwargs = {}
    if thinking:
        extra_kwargs["extra_body"] = {
            "generationConfig": {
                "thinking_config": {"thinking_budget": 2048}
            }
        }

    for attempt in range(STAGE1_RETRIES + 1):
        try:
            if provider == "anthropic":
                resp = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    messages=messages,
                )
                return _AnthropicResponseWrapper(resp.content[0].text)
            else:
                return client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.3,
                    **extra_kwargs,
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
        response = _call_with_retry(client, model, [{"role": "user", "content": prompt}],
                                    provider=STAGE1_PROVIDER)
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


def summarize_category(client, model: str, category: str, events: list[dict],
                       last_digest: dict | None = None) -> dict:
    """
    Stage 2：從聚類後的事件中選 TOP_N，說明為什麼重要，識別跨文章趨勢。
    events 是 clusterer.cluster_articles() 的輸出，每個 element 有
    representative, related, cluster_size。
    last_digest 有值時，在 prompt 末尾加入上週資料，並要求 LLM 輸出 cross_week。
    """
    if not events:
        return {"trend": "", "articles": [], "cross_week": None}

    lines = []
    for i, event in enumerate(events):
        rep  = event["representative"]
        size = event["cluster_size"]
        line = (
            f"{i+1}. 標題：{rep['title']}\n"
            f"   來源：{rep['source']}\n"
            f"   摘要：{rep['key_points']}\n"
            f"   連結：{rep['url']}"
        )
        if size > 1:
            related_titles = "、".join(r["title"] for r in event["related"])
            line += f"\n   相關報導（{size - 1} 篇）：{related_titles}"
        lines.append(line)
    summary_list = "\n".join(lines)

    # 基礎 prompt（不含跨週部分）
    prompt = f"""你是資深{category}新聞編輯。報導數量越多的事件通常越重要，請將報導密度納入排名考量。以下是本週各篇新聞的摘要分析：

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

    # 有上週資料時，插入跨週 context 並擴充 JSON schema
    if last_digest is not None:
        last_titles = "\n".join([
            f"{i+1}. {a['title']}"
            for i, a in enumerate(last_digest.get("articles", []))
        ])
        cross_week_section = f"""
---
以下是上週（{last_digest['run_date']}）的 {category} 週報供你參考：
上週趨勢：{last_digest['trend']}
上週 TOP{TOP_N}：
{last_titles}

請額外分析跨週變化，在 JSON 中加入：
"cross_week": {{
  "continuing": ["延續上週的趨勢或議題（1-2項）"],
  "emerging": ["本週新出現的重要議題（1-2項）"]
}}"""
        # 插在「只回傳 JSON」之前
        prompt = prompt.replace(
            "\n只回傳 JSON，不要其他說明。",
            cross_week_section + "\n\n只回傳 JSON，不要其他說明。"
        )

    try:
        use_thinking = STAGE2_THINKING and STAGE2_PROVIDER == "gemini"
        response = _call_with_retry(client, model, [{"role": "user", "content": prompt}],
                                    provider=STAGE2_PROVIDER, thinking=use_thinking)
        raw      = response.choices[0].message.content.strip()
        raw      = raw.replace("```json", "").replace("```", "").strip()
        result   = json.loads(raw)

        if isinstance(result, dict):
            trend      = result.get("trend", "")
            articles   = result.get("articles", next(iter(result.values()), []))
            cross_week = result.get("cross_week") if last_digest is not None else None
        else:
            trend, articles, cross_week = "", result, None

        if trend:
            print(f"   📈 趨勢：{trend}")
            logging.info(f"{category} 趨勢：{trend}")
        if cross_week:
            print(f"   🔄 跨週觀察：延續 {len(cross_week.get('continuing', []))} 項，新興 {len(cross_week.get('emerging', []))} 項")

        print(f"   ✅ AI 完成 {category} TOP{TOP_N} 整理")
        return {"trend": trend, "articles": articles, "cross_week": cross_week}

    except Exception as e:
        logging.error(f"Stage 2 失敗 ({category}): {e}")
        print(f"   ❌ 失敗：{e}")
        return {"trend": "", "articles": [], "cross_week": None}


def run():
    print(f"\n{'='*50}")
    print(f"📊 Pipeline B 開始 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    init_db()
    stage1_client, stage1_model = get_ai_client(STAGE1_PROVIDER, STAGE1_MODEL)
    stage2_client, stage2_model = get_ai_client(STAGE2_PROVIDER, STAGE2_MODEL)
    all_articles  = get_recent_articles(days=7)
    total         = len(all_articles)
    print(f"\n📦 共撈到 {total} 篇文章")

    if not all_articles:
        print("⚠️  無文章，Pipeline B 結束")
        logging.warning("Pipeline B：無文章可處理")
        return

    # 依分類分組（DB 原始文章，有 title + summary，無 key_points）
    by_category: dict[str, list[dict]] = defaultdict(list)
    for a in all_articles:
        by_category[a["category"]].append(a)

    run_date = datetime.now().strftime("%Y-%m-%d")

    # 聚類（在 Stage 1 之前，對原始文章做；clusterer 支援 fallback 到 summary）
    clusterer = NewsClusterer()
    clustered_by_category: dict[str, list[dict]] = {}
    for category, sums in by_category.items():
        print(f"\n   🔗 聚類 {category}（{len(sums)} 篇）...")
        clustered_by_category[category] = clusterer.cluster_articles(sums, distance_threshold=0.55)[:30]

    # 從所有事件提取 representatives，組成 flat list 供 Stage 1 使用
    representatives: list[dict] = []
    for events in clustered_by_category.values():
        for event in events:
            representatives.append(event["representative"])

    n_clusters        = sum(len(evts) for evts in clustered_by_category.values())
    n_representatives = len(representatives)

    # Stage 1：只對 representatives 做 LLM 摘要
    stage1_results = run_stage1(stage1_client, stage1_model, representatives)
    n_success      = len(stage1_results)

    print(f"\n📊 漏斗：{total}篇 → {n_clusters}個事件 → {n_representatives}篇進 Stage 1 → {n_success}篇成功")
    logging.info(f"漏斗：{total} → {n_clusters}事件 → {n_representatives}篇 → {n_success}成功")

    if not stage1_results:
        print("⚠️  Stage 1 無成功結果，Pipeline B 結束")
        logging.warning("Pipeline B：Stage 1 無成功結果")
        return

    # 把 stage1 結果回掛到對應 event 的 representative（O(1) lookup by URL）
    stage1_by_url: dict[str, dict] = {r["url"]: r for r in stage1_results}

    for category, events in clustered_by_category.items():
        enriched_events = []
        for event in events:
            rep = event["representative"]
            s1  = stage1_by_url.get(rep["url"])
            if s1 is None:
                # Stage 1 失敗的 representative → 移除整個 event
                continue
            # 把 key_points 寫回 representative，其餘欄位保留原值
            rep["key_points"] = s1["key_points"]
            enriched_events.append(event)
        clustered_by_category[category] = enriched_events

    # Stage 2：跨文章選 TOP5 + 識別趨勢 + 跨週比較
    print(f"\n🏆 Stage 2：跨文章排名（{len(clustered_by_category)} 個分類）")
    summaries: dict = {}
    for category, events in clustered_by_category.items():
        last_digest = get_last_weekly_digest(category)
        if last_digest:
            print(f"\n   🔍 處理 {category}（{len(events)} 個事件，有上週資料：{last_digest['run_date']}）...")
        else:
            print(f"\n   🔍 處理 {category}（{len(events)} 個事件，無上週資料）...")
        summaries[category] = summarize_category(stage2_client, stage2_model, category, events,
                                                  last_digest=last_digest)

    # 存入本週週報（供下週跨週比較使用）
    for category, v in summaries.items():
        save_weekly_digest(run_date, category, v.get("trend", ""), v.get("articles", []))
    print(f"\n💾 本週週報已存入 DB（run_date={run_date}）")
    logging.info(f"本週週報存入 DB，run_date={run_date}")

    # Stage 3：訊號追蹤（用有 key_points 的 representatives）
    topic_signals: dict = {}
    if TRACKED_TOPICS:
        print(f"\n📡 訊號追蹤（{len(TRACKED_TOPICS)} 個主題）")
        topic_hits = clusterer.track_topics(stage1_results, TRACKED_TOPICS, TOPIC_SIMILARITY_THRESHOLD)
        for topic, matched in topic_hits.items():
            hit_count = len(matched)
            hit_urls  = [a["url"] for a in matched]
            last      = get_last_topic_signal(topic)
            save_topic_signal(run_date, topic, hit_count, hit_urls)
            previous  = last["hit_count"] if last else None
            if previous is None:
                trend = "🆕"
            elif hit_count > previous:
                trend = "↑"
            elif hit_count < previous:
                trend = "↓"
            else:
                trend = "→"
            topic_signals[topic] = {"current": hit_count, "previous": previous, "trend": trend}
        logging.info(f"訊號追蹤完成：{topic_signals}")

    html = build_email_html(summaries, topic_signals=topic_signals)
    send_email(html)

    total_top = sum(len(v["articles"]) for v in summaries.values())
    print(f"\n🎉 Pipeline B 完成！共選出 {total_top} 篇文章進入週報")
    logging.info(f"Pipeline B 完成，週報共 {total_top} 篇")


if __name__ == "__main__":
    run()
