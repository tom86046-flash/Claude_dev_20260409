"""
Line Notify 推播模組
"""
import logging
import os
from datetime import datetime

import httpx

from taiwan_discounts.models.discount import Discount

logger = logging.getLogger(__name__)

LINE_NOTIFY_API = "https://notify-api.line.me/api/notify"


def build_message(discounts: list[Discount]) -> str:
    if not discounts:
        return "\n目前沒有符合條件的高價值優惠。"

    urgent = [d for d in discounts if d.urgency_days is not None and d.urgency_days <= 3]
    normal = [d for d in discounts if not (d.urgency_days is not None and d.urgency_days <= 3)]

    lines = [f"\n🔥 今日必搶優惠 {datetime.now().strftime('%m/%d %H:%M')} 更新\n"]

    if urgent:
        lines.append("⏰ 即將到期（3天內）")
        for d in urgent:
            date_str = d.deadline.strftime("%m/%d") if d.deadline else "長期"
            lines.append(f"• 【{d.platform.value}】{d.title}")
            lines.append(f"  💰 {d.discount_amount}　📅 {date_str}（剩{d.urgency_days}天）")
            lines.append(f"  {d.url}")

    if normal:
        if urgent:
            lines.append("")
        lines.append("💰 高折扣優惠")
        for d in normal[:8]:  # Line Notify 有字數限制
            date_str = d.deadline.strftime("%m/%d") if d.deadline else "長期"
            lines.append(f"• 【{d.platform.value}】{d.title}")
            lines.append(f"  💰 {d.discount_amount}　📅 {date_str}")

    if len(normal) > 8:
        lines.append(f"\n...還有 {len(normal) - 8} 筆優惠，請至網頁查看")

    return "\n".join(lines)


async def send_line_notify(discounts: list[Discount], selected_ids: list[str] | None = None) -> bool:
    """
    推播優惠到 Line Notify。
    selected_ids: 若指定，只推播這些 ID 的優惠；否則推播全部。
    """
    token = os.getenv("LINE_NOTIFY_TOKEN")

    if not token:
        logger.error("LINE_NOTIFY_TOKEN 未設定")
        return False

    if selected_ids is not None:
        discounts = [d for d in discounts if d.id in selected_ids]

    message = build_message(discounts)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                LINE_NOTIFY_API,
                headers={"Authorization": f"Bearer {token}"},
                data={"message": message},
            )
            if resp.status_code != 200:
                logger.error(f"Line Notify API 錯誤：{resp.status_code} {resp.text}")
                return False
            return True
    except Exception as e:
        logger.error(f"Line Notify 推播失敗：{e}")
        return False
