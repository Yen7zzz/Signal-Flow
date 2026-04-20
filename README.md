# 📰 SignalFlow — AI 驅動的新聞週報系統

每天自動抓新聞、語意分群，每週一早上寄出 Anthropic AI 整理的深度摘要 Email。

---

## 檔案結構

```
SignalFlow/
├── config.py                    ← 環境變數讀取與全域設定
├── database.py                  ← SQLite 操作（dedup、查詢、weekly_digests）
├── classifier.py                ← Transformer zero-shot 分類器
├── clusterer.py                 ← AgglomerativeClustering 文章分群
├── scraper.py                   ← 全文抓取（trafilatura + newspaper3k fallback）
├── pipeline_a.py                ← 每日：RSS 抓取 → 去重 → 存 DB（基本版）
├── pipeline_a_transformer.py    ← 每日：加入語意篩選 + 全文抓取（推薦）
├── pipeline_b.py                ← 每週：分群 → AI 摘要 → 寄信
├── scheduler.py                 ← 本機自動排程主程式
├── evaluate_threshold.py        ← 調整分類器門檻工具
├── diagnose_fulltext.py         ← 全文抓取診斷工具
├── test_scraper.py              ← scraper 測試
├── test_track_topics.py         ← 主題趨勢追蹤測試
├── requirements.txt
├── .github/workflows/
│   ├── daily_collect.yml        ← 每日 UTC 22:00 執行 Pipeline A
│   └── weekly_digest.yml        ← 每週日 UTC 22:00（台灣週一 06:00）執行 Pipeline B
├── data/                        ← news.db 自動建立並由 CI 維護
└── logs/                        ← 執行紀錄
```

---

## 安裝步驟

```bash
# 1. 安裝套件
pip install -r requirements.txt

# 2. 設定環境變數
export ANTHROPIC_API_KEY=your_key
export EMAIL_SENDER=your_gmail@gmail.com
export EMAIL_PASSWORD=your_app_password   # 見下方說明
export EMAIL_RECEIVERS=a@example.com,b@example.com

# 3. 啟動排程
python scheduler.py
```

---

## Gmail App Password 設定

`EMAIL_PASSWORD` 不是 Gmail 登入密碼，而是 **App Password**：

1. Google 帳號 → 安全性
2. 開啟兩步驟驗證
3. 搜尋「應用程式密碼」→ 產生一組 16 碼密碼
4. 將這 16 碼設為 `EMAIL_PASSWORD` 環境變數

---

## 手動執行

```bash
# Pipeline A：抓新聞（含語意篩選，推薦）
python pipeline_a_transformer.py

# Pipeline B：生成週報並寄信
python pipeline_b.py

# 工具
python evaluate_threshold.py   # 調整分類門檻
python diagnose_fulltext.py    # 診斷全文抓取覆蓋率
```

---

## 流程圖

```
Pipeline A（每日 UTC 22:00）
  RSS feeds
    → feedparser 解析
    → Transformer zero-shot 分類篩選（cross-encoder/nli-MiniLM2-L6-H768）
    → MD5 去重
    → SQLite 儲存
    → 全文抓取（trafilatura / newspaper3k）

Pipeline B（每週日 UTC 22:00 = 台灣週一 06:00）
  SQLite 撈最近 7 天文章
    → AgglomerativeClustering 語意分群（all-MiniLM-L6-v2）
    → Stage 1：Haiku 批次摘要（成本效率優先）
    → Stage 2：Sonnet 排名 + 趨勢分析（品質優先）
    → 組成 HTML Email
    → Gmail SMTP 寄出
```

---

## GitHub Actions Secrets

| Secret | 用途 |
|--------|------|
| `ANTHROPIC_API_KEY` | Stage 1 (Haiku) + Stage 2 (Sonnet) |
| `EMAIL_SENDER` | Gmail 寄件帳號 |
| `EMAIL_PASSWORD` | Gmail App Password |
| `EMAIL_RECEIVERS` | 收件人（逗號分隔） |
| `GEMINI_API_KEY` | 備用（workflow env 保留） |
