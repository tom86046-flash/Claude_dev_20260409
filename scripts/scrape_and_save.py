"""
獨立爬取腳本：爬取所有平台優惠，輸出 docs/discounts.json
供 GitHub Actions 使用
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 讓 src 可以被 import
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv()

from taiwan_discounts.aggregator.engine import fetch_all_discounts
from taiwan_discounts.notifiers.telegram import send_telegram
from taiwan_discounts.notifiers.line_notify import send_line_notify


async def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 開始爬取...")

    result = await fetch_all_discounts(filter_high_value=True)
    discounts = result["all"]
    errors = result.get("errors", {})

    print(f"爬取完成：共 {len(discounts)} 筆高價值優惠")
    if errors:
        for platform, err in errors.items():
            print(f"  ⚠️  {platform} 爬取失敗：{err}")

    # 轉成 JSON-serializable 格式
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(discounts),
        "errors": errors,
        "discounts": [d.model_dump(mode="json") for d in discounts],
    }

    # 儲存到 docs/discounts.json（GitHub Pages 會讀這個）
    out_path = Path(__file__).parent.parent / "docs" / "discounts.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"已儲存到 {out_path}")

    # 推播通知（若有設定 token）
    notify_mode = os.getenv("NOTIFY_MODE", "").lower()  # "telegram" | "line" | "both" | ""

    if notify_mode in ("telegram", "both") and os.getenv("TELEGRAM_BOT_TOKEN"):
        ok = await send_telegram(discounts)
        print("Telegram 推播：", "成功" if ok else "失敗")

    if notify_mode in ("line", "both") and os.getenv("LINE_NOTIFY_TOKEN"):
        ok = await send_line_notify(discounts)
        print("Line Notify 推播：", "成功" if ok else "失敗")

    print("完成！")


if __name__ == "__main__":
    asyncio.run(main())
