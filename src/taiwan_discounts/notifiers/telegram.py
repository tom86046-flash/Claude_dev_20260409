"""
Telegram Bot 推播模組
"""
import logging
import os
from datetime import datetime

import httpx

from taiwan_discounts.models.discount import Discount

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


def _format_discount(d: Discount, index: int) -> str:
    lines = [f"*{index}. 【{d.platform.value}】{d.title}*"]
    lines.append(f"💰 折扣：{d.discount_amount}")

    if d.deadline:
        date_str = d.deadline.strftime("%m/%d")
        if d.urgency_days is not None and d.urgency_days <= 3:
            lines.append(f"📅 截止：{date_str} ⚠️ 還有 {d.urgency_days} 天！")
        else:
            lines.append(f"📅 截止：{date_str}")
    else:
        lines.append("📅 截止：長期活動")

    if d.conditions:
        lines.append(f"📋 條件：{' / '.join(d.conditions[:2])}")

    lines.append(f"🔗 [查看詳情]({d.url})")
    return "\n".join(lines)


def build_message(discounts: list[Discount]) -> str:
    if not discounts:
        return "目前沒有符合條件的高價值優惠。"

    urgent = [d for d in discounts if d.urgency_days is not None and d.urgency_days <= 3]
    normal = [d for d in discounts if not (d.urgency_days is not None and d.urgency_days <= 3)]

    parts = [f"🔥 *今日必搶優惠* — {datetime.now().strftime('%m/%d %H:%M')} 更新\n"]

    idx = 1
    if urgent:
        parts.append("⏰ *即將到期（3天內）*")
        for d in urgent:
            parts.append(_format_discount(d, idx))
            idx += 1

    if normal:
        if urgent:
            parts.append("")
        parts.append("💰 *高折扣優惠*")
        for d in normal[:10]:  # 最多顯示10筆
            parts.append(_format_discount(d, idx))
            idx += 1

    if len(normal) > 10:
        parts.append(f"\n_...還有 {len(normal) - 10} 筆優惠，請至網頁查看_")

    return "\n\n".join(parts)


async def send_telegram(discounts: list[Discount], selected_ids: list[str] | None = None) -> bool:
    """
    推播優惠到 Telegram。
    selected_ids: 若指定，只推播這些 ID 的優惠；否則推播全部。
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未設定")
        return False

    if selected_ids is not None:
        discounts = [d for d in discounts if d.id in selected_ids]

    message = build_message(discounts)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{TELEGRAM_API}/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                },
            )
            if resp.status_code != 200:
                logger.error(f"Telegram API 錯誤：{resp.status_code} {resp.text}")
                return False
            return True
    except Exception as e:
        logger.error(f"Telegram 推播失敗：{e}")
        return False
