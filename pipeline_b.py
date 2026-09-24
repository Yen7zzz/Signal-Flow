# ============================================================
# pipeline_b.py — 每週執行：撈新聞 → 全量聚類 → 產出 Evidence Pack → 寄附件
#
# 不做 LLM 摘要／排名／判斷。只搬運與標註 DB 原始資料，
# 產出結構化 Markdown（digests/YYYY-MM-DD.md）給下游 LLM 交叉驗證。
# 訊號追蹤（track_topics）是本機關鍵字/語意比對，非 LLM 判斷，保留。
# ============================================================

import sys
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta
from collections import defaultdict

import config
from clusterer import NewsClusterer
from database import (
    init_db, get_recent_articles, save_weekly_digest,
    save_topic_signal, get_last_topic_signal,
)

import os
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/pipeline_b.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

FULLTEXT_MIN_LEN = 200   # full_text 超過此長度才視為「已抓取」
WARNINGS_FILE = "digest_warnings.txt"   # 有軟警告時寫入，供 workflow 最後一步判定失敗


def get_source_tier(source: str) -> int:
    """依 config.SOURCE_TIERS 做小寫 substring 比對，找不到則回傳 SOURCE_TIER_DEFAULT"""
    s = (source or "").lower()
    for keyword, tier in config.SOURCE_TIERS.items():
        if keyword in s:
            return tier
    return config.SOURCE_TIER_DEFAULT


def format_published_date(published: str, created_at: str = "") -> str:
    """把 RSS published 字串轉成 YYYY-MM-DD；解析失敗 fallback 到 created_at；兩者都無則「未知」"""
    published = (published or "").strip()
    if published:
        try:
            return parsedate_to_datetime(published).strftime("%Y-%m-%d")
        except Exception:
            pass
        try:
            return datetime.fromisoformat(published.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except Exception:
            pass

    created_at = (created_at or "").strip()
    if len(created_at) >= 10:
        return created_at[:10]

    return "未知"


def dedup_sources(articles: list[dict]) -> str:
    """去重 source 並各自標註 tier，格式：Name (T1) / Name2 (T2)"""
    seen = []
    for a in articles:
        source = (a.get("source") or "").strip()
        if source and source not in seen:
            seen.append(source)
    if not seen:
        return "未知"
    return " / ".join(f"{s} (T{get_source_tier(s)})" for s in seen)


def render_markdown(clustered_by_category: dict, stats: dict, topic_signals: dict | None = None,
                    warnings: list[str] | None = None,
                    unclassified_events: list[dict] | None = None) -> str:
    """
    產出 Evidence Pack Markdown。
    clustered_by_category: {category: events}，events 是 clusterer.cluster_articles() 的輸出（不含未分類）
    stats: {run_date, start_date, end_date, total_articles, total_events, fulltext_coverage,
            total_unclassified, unclassified_events}
    topic_signals: {topic: {"current": int, "previous": int|None, "trend": str}}
    warnings: 本週資料警告（聚類失敗、文章數過少等），有才輸出警告區塊
    unclassified_events: 未分類文章的聚類結果，以精簡格式放在報告最後
    只搬運與標註，不改寫、不排名、不下判斷、不壓縮。
    """
    uncl = config.UNCLASSIFIED_CATEGORY
    lines = []
    lines.append(f"# SignalFlow Evidence Pack — {stats['run_date']}")
    lines.append("")
    if warnings:
        for w in warnings:
            lines.append(f"> ⚠️ 本週資料警告：{w}")
        lines.append("")
    lines.append("> **資料性質**：未經 LLM 處理的原始新聞聚合。所有標題與摘要皆為媒體原文，未經改寫。")
    lines.append(f"> **收錄期間**：{stats['start_date']} ~ {stats['end_date']}")
    n_uncl = stats.get("total_unclassified", 0)
    uncl_note = (
        f"（另有{uncl} {n_uncl} 篇 → {stats.get('unclassified_events', 0)} 群，列於報告最後）" if n_uncl else ""
    )
    lines.append(f"> **原始文章數**：{stats['total_articles']}｜聚類後事件數：{stats['total_events']}{uncl_note}")
    lines.append(
        f"> **全文抓取覆蓋率**：{stats['fulltext_coverage']:.0%}"
        f"（標記 ⚠️ 者僅有 RSS 摘要，內容可能不完整，建議搜尋原文）"
    )
    lines.append("> **來源分級**：T1=通訊社/即時財經（一手）　T2=主流報紙/廣電（採訪為主）　T3=專業媒體/評論/聚合（多為二手或分析）。此為報導性質分類，非品質評分。")
    lines.append("> **排序依據**：報導數（cluster_size）由多到少，**非重要性判斷**")
    lines.append(
        f"> **分類說明**：由本機 zero-shot 分類器判定；最高分低於 {config.CLASSIFIER_THRESHOLD} 的文章歸入「{uncl}」，"
        f"列於報告最後（精簡格式、未抓全文、不計入訊號追蹤與上方文章數）。"
    )
    lines.append("> 各分類內仍可能混入不相關主題，請自行判讀")
    lines.append("")

    for category, events in clustered_by_category.items():
        n_articles = sum(e["cluster_size"] for e in events)
        lines.append(f"## {category}（{n_articles} 篇 → {len(events)} 個事件）")
        lines.append("")

        for i, event in enumerate(events, 1):
            rep = event["representative"]
            related = event["related"]
            size = event["cluster_size"]
            all_in_cluster = [rep] + related

            full_text = rep.get("full_text") or ""
            fulltext_status = "✅ 已抓取" if len(full_text) > FULLTEXT_MIN_LEN else "⚠️ 僅 RSS 摘要"

            lines.append(f"### {i}. {rep.get('title', '(無標題)')}")
            lines.append(f"- **報導數**：{size}")
            lines.append(f"- **來源**：{dedup_sources(all_in_cluster)}")
            lines.append(f"- **發布時間**：{format_published_date(rep.get('published'), rep.get('created_at'))}")
            lines.append(f"- **全文**：{fulltext_status}")
            lines.append(f"- **摘要**：{rep.get('summary') or ''}")
            lines.append(f"- **連結**：{rep.get('url', '')}")
            if size > 1:
                lines.append("- **同群報導**：")
                for r in related:
                    lines.append(f"  - {r.get('title', '')} — {r.get('url', '')}")
            lines.append("")

    if topic_signals:
        lines.append("## 📡 訊號追蹤（本機關鍵字比對，非 LLM 判斷）")
        lines.append("")
        lines.append("| 主題 | 本週 | 上週 | 變化 |")
        lines.append("|---|---|---|---|")
        for topic, sig in topic_signals.items():
            prev = sig["previous"] if sig["previous"] is not None else "—"
            lines.append(f"| {topic} | {sig['current']} | {prev} | {sig['trend']} |")
        lines.append("")

    if unclassified_events:
        lines.append(f"## {uncl}（{n_uncl} 篇 → {len(unclassified_events)} 群，精簡格式）")
        lines.append("")
        lines.append(f"> 分類器最高分低於 {config.CLASSIFIER_THRESHOLD}，可能是雜訊，也可能是跨領域新聞；未抓全文，不列摘要")
        lines.append("")
        for i, event in enumerate(unclassified_events, 1):
            rep = event["representative"]
            related = event["related"]
            lines.append(f"### {i}. {rep.get('title', '(無標題)')}")
            lines.append(f"- **來源**：{dedup_sources([rep] + related)}")
            lines.append(f"- **連結**：{rep.get('url', '')}")
            if related:
                lines.append("- **同群報導**：")
                for r in related:
                    lines.append(f"  - {r.get('title', '')}")
            lines.append("")

    return "\n".join(lines)


def save_digest_file(markdown: str, run_date: str) -> str:
    os.makedirs("digests", exist_ok=True)
    path = os.path.join("digests", f"{run_date}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)
    return path


def send_email(run_date: str, total_articles: int, total_events: int, attachment_path: str,
               total_unclassified: int = 0, unclassified_events: int = 0):
    receivers = [r.strip() for r in config.EMAIL_RECEIVERS.split(",") if r.strip()]

    msg = MIMEMultipart()
    msg["Subject"] = f"SignalFlow Evidence Pack {run_date}"
    msg["From"] = config.EMAIL_SENDER
    msg["To"] = ", ".join(receivers)

    unclassified_note = (
        f"另有{config.UNCLASSIFIED_CATEGORY} {total_unclassified} 篇 → {unclassified_events} 群（列於附件最後）。\n"
        if total_unclassified else ""
    )
    body = (
        f"本週收錄 {total_articles} 篇文章，聚類為 {total_events} 個事件。\n"
        f"{unclassified_note}"
        f"完整內容見附件。\n"
        f"GitHub: {config.GITHUB_DIGEST_BASE_URL}{run_date}.md"
    )
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with open(attachment_path, "rb") as f:
        attachment = MIMEApplication(f.read(), _subtype="markdown")
    attachment.add_header(
        "Content-Disposition", "attachment", filename=os.path.basename(attachment_path)
    )
    attachment.set_type("text/markdown")
    attachment.set_param("charset", "utf-8")
    msg.attach(attachment)

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
        server.starttls()
        server.login(config.EMAIL_SENDER, config.EMAIL_PASSWORD)
        server.sendmail(config.EMAIL_SENDER, receivers, msg.as_string())

    print(f"📧 Email 已寄出 → {receivers}")
    logging.info(f"Email 寄出成功 → {receivers}")


def compute_topic_signals(clusterer: NewsClusterer, representatives: list[dict],
                          run_date: str, dry_run: bool) -> dict:
    """
    用 representatives（每個事件的代表文章）做 track_topics，
    對照上週的 hit_count 算出變化趨勢。dry_run 時不寫入 DB。
    """
    if not config.TRACKED_TOPICS or not representatives:
        return {}

    print(f"\n📡 訊號追蹤（{len(config.TRACKED_TOPICS)} 個主題）")
    topic_hits = clusterer.track_topics(
        representatives, config.TRACKED_TOPICS, config.TOPIC_SIMILARITY_THRESHOLD
    )

    topic_signals: dict = {}
    for topic, matched in topic_hits.items():
        hit_count = len(matched)
        hit_urls = [a.get("url", "") for a in matched]
        last = get_last_topic_signal(topic)
        previous = last["hit_count"] if last else None

        if not dry_run:
            save_topic_signal(run_date, topic, hit_count, hit_urls)

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
    return topic_signals


def run(dry_run: bool = False):
    print(f"\n{'='*50}")
    print(f"📊 Pipeline B 開始 — {datetime.now().strftime('%Y-%m-%d %H:%M')}" + ("（--dry-run）" if dry_run else ""))
    print(f"{'='*50}")

    init_db()
    all_articles = get_recent_articles(days=7)
    uncl = config.UNCLASSIFIED_CATEGORY
    classified_articles = [a for a in all_articles if a["category"] != uncl]
    total = len(classified_articles)             # 正常分類文章數（不含未分類）
    total_unclassified = len(all_articles) - total
    print(f"\n📦 共撈到 {len(all_articles)} 篇文章（正常分類 {total} 篇，{uncl} {total_unclassified} 篇）")

    if not all_articles:
        print("❌ 無文章，Pipeline B 失敗結束")
        logging.error("Pipeline B：無文章可處理")
        sys.exit(1)

    warnings: list[str] = []
    if total < config.MIN_WEEKLY_ARTICLES:
        warnings.append(f"本週文章數 {total} 篇，低於門檻 {config.MIN_WEEKLY_ARTICLES} 篇，每日收集可能連續失敗")

    by_category: dict[str, list[dict]] = defaultdict(list)
    for a in all_articles:
        by_category[a["category"]].append(a)

    run_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    try:
        clusterer = NewsClusterer()
    except Exception as e:
        print(f"❌ NewsClusterer 初始化失敗：{e}")
        logging.error(f"NewsClusterer 初始化失敗：{e}")
        sys.exit(1)

    clustered_by_category: dict[str, list[dict]] = {}
    for category, arts in by_category.items():
        print(f"\n   🔗 聚類 {category}（{len(arts)} 篇）...")
        try:
            clustered_by_category[category] = clusterer.cluster_articles(
                arts, distance_threshold=config.CLUSTER_DISTANCE_THRESHOLD
            )
        except Exception as e:
            print(f"   ❌ 聚類 {category} 失敗：{e}")
            logging.error(f"cluster_articles 失敗 ({category})：{e}")
            clustered_by_category[category] = []
            warnings.append(f"{category} 聚類失敗（{len(arts)} 篇未列入）：{e}")

    print("\n📊 各分類事件數：" + "、".join(
        f"{cat} {len(evts)} 個事件" for cat, evts in clustered_by_category.items()
    ))

    # 未分類獨立出來：不計入事件數、全文覆蓋率、訊號追蹤，報告中放在最後
    unclassified_events = clustered_by_category.pop(uncl, [])

    total_events = sum(len(evts) for evts in clustered_by_category.values())
    n_fulltext = sum(1 for a in classified_articles if len(a.get("full_text") or "") > FULLTEXT_MIN_LEN)
    fulltext_coverage = n_fulltext / total if total else 0.0

    print(f"\n📊 漏斗：{total} 篇 → {total_events} 個事件（全文覆蓋率 {fulltext_coverage:.0%}）"
          f"；{uncl} {total_unclassified} 篇 → {len(unclassified_events)} 群")
    logging.info(f"漏斗：{total} 篇 → {total_events} 個事件，全文覆蓋率 {fulltext_coverage:.0%}；"
                 f"{uncl} {total_unclassified} 篇 → {len(unclassified_events)} 群")

    # 訊號追蹤：用每個事件的 representative（不含未分類）
    representatives = [
        event["representative"]
        for events in clustered_by_category.values()
        for event in events
    ]
    topic_signals = compute_topic_signals(clusterer, representatives, run_date, dry_run)

    stats = {
        "run_date": run_date,
        "start_date": start_date,
        "end_date": run_date,
        "total_articles": total,
        "total_events": total_events,
        "fulltext_coverage": fulltext_coverage,
        "total_unclassified": total_unclassified,
        "unclassified_events": len(unclassified_events),
    }

    markdown = render_markdown(clustered_by_category, stats, topic_signals=topic_signals, warnings=warnings,
                               unclassified_events=unclassified_events)
    path = save_digest_file(markdown, run_date)
    print(f"📄 Evidence Pack 已存：{path}")

    if warnings:
        print(f"\n⚠️  本週資料警告（{len(warnings)} 條）：")
        for w in warnings:
            print(f"   - {w}")
            logging.warning(f"本週資料警告：{w}")
    else:
        print("\n✅ 無資料警告")

    if dry_run:
        preview_lines = markdown.splitlines()[:60]
        print(f"\n{'='*50}")
        print(f"👀 --dry-run 預覽（前 60 行，共 {len(markdown.splitlines())} 行）")
        print("=" * 50)
        print("\n".join(preview_lines))
        print("=" * 50)
        print("\n⏭️  --dry-run：略過寄信與 DB 寫入（save_weekly_digest / save_topic_signal）")
        logging.info(f"Pipeline B --dry-run 完成，{total} 篇 → {total_events} 個事件")
        return

    # 存入本週週報（供下週跨週比較使用，全量保留，不只前幾名）；未分類另存一列，category 不會混用
    snapshot_items = list(clustered_by_category.items())
    if unclassified_events:
        snapshot_items.append((uncl, unclassified_events))
    for category, events in snapshot_items:
        articles_snapshot = [
            {
                "title": e["representative"].get("title", ""),
                "url": e["representative"].get("url", ""),
                "source": e["representative"].get("source", ""),
                "cluster_size": e["cluster_size"],
            }
            for e in events
        ]
        save_weekly_digest(run_date, category, "", articles_snapshot)
    print(f"\n💾 本週週報已存入 DB（run_date={run_date}）")
    logging.info(f"本週週報存入 DB，run_date={run_date}")

    send_email(run_date, total, total_events, path,
               total_unclassified=total_unclassified, unclassified_events=len(unclassified_events))

    # 寄信與 DB 寫入都完成後才寫警告檔；程式仍以 0 結束，由 workflow 最後一步判定失敗
    if warnings:
        with open(WARNINGS_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(warnings) + "\n")
        print(f"⚠️  資料警告已寫入 {WARNINGS_FILE}")

    print(f"\n🎉 Pipeline B 完成！共 {total} 篇文章 → {total_events} 個事件")
    logging.info(f"Pipeline B 完成，{total} 篇 → {total_events} 個事件")


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
