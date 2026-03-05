# ============================================================
# scheduler.py — 自動排程：每天跑 A，每週一跑 B
# ============================================================

import schedule
import time
import logging
from pipeline_a import run as run_pipeline_a
from pipeline_b import run as run_pipeline_b
import os

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/pipeline_a.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


def job_a():
    print("\n⏰ 排程觸發：Pipeline A（收集新聞）")
    logging.info("Pipeline A 排程觸發")
    run_pipeline_a()


def job_b():
    print("\n⏰ 排程觸發：Pipeline B（週報生成）")
    logging.info("Pipeline B 排程觸發")
    run_pipeline_b()


if __name__ == "__main__":
    print("🚀 Scheduler 啟動中...")
    print("   📥 Pipeline A：每天早上 08:00 執行")
    print("   📧 Pipeline B：每週一早上 09:00 執行")
    print("   按 Ctrl+C 停止\n")

    # 每天早上 8 點抓新聞
    schedule.every().day.at("08:00").do(job_a)

    # 每週一早上 9 點發週報
    schedule.every().monday.at("09:00").do(job_b)

    # 啟動時先跑一次 A，確認設定正確
    print("🔄 啟動時先執行一次 Pipeline A 測試...")
    job_a()

    while True:
        schedule.run_pending()
        time.sleep(60)
