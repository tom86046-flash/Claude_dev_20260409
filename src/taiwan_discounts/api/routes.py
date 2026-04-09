"""
FastAPI 路由
"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from taiwan_discounts.aggregator.engine import fetch_all_discounts
from taiwan_discounts.models.discount import Discount
from taiwan_discounts.notifiers.line_notify import send_line_notify
from taiwan_discounts.notifiers.telegram import send_telegram

logger = logging.getLogger(__name__)
router = APIRouter()

# 記憶體快取（避免每次請求都爬取）
_cache: dict = {"data": None, "loading": False}


async def _refresh_cache():
    _cache["loading"] = True
    try:
        _cache["data"] = await fetch_all_discounts(filter_high_value=True)
    except Exception as e:
        logger.error(f"Refresh cache error: {e}")
    finally:
        _cache["loading"] = False


@router.get("/api/discounts")
async def get_discounts(
    background_tasks: BackgroundTasks,
    min_cashback: Optional[float] = None,
    min_discount: Optional[float] = None,
    platform: Optional[str] = None,
    force_refresh: bool = False,
):
    """取得所有高價值優惠（已篩選 + 排序）"""
    if force_refresh or _cache["data"] is None:
        if not _cache["loading"]:
            await _refresh_cache()
        if _cache["data"] is None:
            return {"all": [], "urgent": [], "errors": {}, "total": 0, "loading": True}

    data = _cache["data"]
    discounts: list[Discount] = data["all"]

    # 套用前端傳入的自訂門檻
    if min_cashback is not None:
        from decimal import Decimal
        discounts = [d for d in discounts if d.discount_value_pct and d.discount_value_pct >= Decimal(str(min_cashback))]

    if platform:
        discounts = [d for d in discounts if platform.lower() in d.platform.value.lower()]

    urgent = [d for d in discounts if d.urgency_days is not None and d.urgency_days <= 3]

    return {
        "all": [d.model_dump(mode="json") for d in discounts],
        "urgent": [d.model_dump(mode="json") for d in urgent],
        "errors": data.get("errors", {}),
        "total": len(discounts),
        "loading": _cache["loading"],
    }


class NotifyRequest(BaseModel):
    selected_ids: Optional[list[str]] = None  # None = 全部推播


@router.post("/api/notify/telegram")
async def notify_telegram(req: NotifyRequest):
    """推播選取的優惠到 Telegram"""
    if _cache["data"] is None:
        raise HTTPException(status_code=503, detail="資料尚未載入，請先呼叫 /api/discounts")

    discounts = _cache["data"]["all"]
    ok = await send_telegram(discounts, selected_ids=req.selected_ids)
    if not ok:
        raise HTTPException(status_code=500, detail="Telegram 推播失敗，請確認 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID 設定")
    return {"ok": True, "message": "推播成功"}


@router.post("/api/notify/line")
async def notify_line(req: NotifyRequest):
    """推播選取的優惠到 Line Notify"""
    if _cache["data"] is None:
        raise HTTPException(status_code=503, detail="資料尚未載入，請先呼叫 /api/discounts")

    discounts = _cache["data"]["all"]
    ok = await send_line_notify(discounts, selected_ids=req.selected_ids)
    if not ok:
        raise HTTPException(status_code=500, detail="Line Notify 推播失敗，請確認 LINE_NOTIFY_TOKEN 設定")
    return {"ok": True, "message": "推播成功"}


@router.post("/api/refresh")
async def refresh_discounts(background_tasks: BackgroundTasks):
    """手動觸發重新爬取"""
    if _cache["loading"]:
        return {"ok": False, "message": "正在爬取中，請稍後"}
    background_tasks.add_task(_refresh_cache)
    return {"ok": True, "message": "已開始重新爬取，請稍後再重新整理頁面"}
