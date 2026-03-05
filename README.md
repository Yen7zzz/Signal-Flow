# 📰 RSS 週報系統

每天自動抓新聞，每週一寄出 AI 整理的 TOP5 摘要 Email。

---

## 檔案結構

```
news_digest/
├── config.py        ← ⭐ 只需要改這個
├── database.py      ← SQLite 資料庫操作
├── pipeline_a.py    ← 每天執行：抓新聞存 DB
├── pipeline_b.py    ← 每週執行：AI 摘要 + 寄 Email
├── scheduler.py     ← 自動排程主程式
├── requirements.txt
├── data/            ← 資料庫檔案自動建立
└── logs/            ← 執行紀錄
```

---

## 安裝步驟

```bash
# 1. 安裝套件
pip install -r requirements.txt

# 2. 設定 config.py
#    填入：OpenAI API Key、Gmail 帳號密碼、收件信箱

# 3. 啟動
python scheduler.py
```

---

## Gmail 設定注意事項

EMAIL_PASSWORD 不是你的 Gmail 登入密碼，而是 **App Password**：

1. Google 帳號 → 安全性
2. 開啟兩步驟驗證
3. 搜尋「應用程式密碼」→ 產生一組 16 碼密碼
4. 把這 16 碼填入 config.py 的 EMAIL_PASSWORD

---

## 手動執行（測試用）

```bash
# 只跑 Pipeline A（抓新聞）
python pipeline_a.py

# 只跑 Pipeline B（生成週報並寄信）
python pipeline_b.py
```

---

## 流程圖

```
Pipeline A（每天 08:00）
  RSS feeds → feedparser 解析 → 去重 → SQLite

Pipeline B（每週一 09:00）
  SQLite 撈 7 天資料
    → GPT-4o-mini 挑 TOP5 + 中文摘要
    → 組成 HTML Email
    → Gmail SMTP 寄出
```
