"""
優惠聚合引擎：同時執行所有爬蟲、篩選高價值優惠、排序
"""
import asyncio
import logging
import os
from decimal import Decimal

from playwright.async_api import async_playwright

from taiwan_discounts.models.discount import Discount, ScrapeResult
from taiwan_discounts.scrapers.hami import scrape_hami
from taiwan_discounts.scrapers.ipass import scrape_ipass
from taiwan_discounts.scrapers.linepay import scrape_linepay

logger = logging.getLogger(__name__)

# 篩選門檻（從環境變數讀取，有預設值）
MIN_CASHBACK_PCT = Decimal(os.getenv("MIN_CASHBACK_PCT", "5"))
MIN_DISCOUNT_PCT = Decimal(os.getenv("MIN_DISCOUNT_PCT", "20"))
MIN_POINTS_MULTIPLIER = Decimal(os.getenv("MIN_POINTS_MULTIPLIER", "3"))
PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"


def is_high_value(discount: Discount) -> bool:
    """判斷是否為高價值優惠（值得搶的）"""
    # 高現金回饋
    if discount.discount_value_pct and discount.discount_value_pct >= MIN_CASHBACK_PCT:
        return True
    # 高折扣（20% 以上）
    if discount.discount_value_pct and discount.discount_value_pct >= MIN_DISCOUNT_PCT:
        return True
    # 高倍點數
    if discount.points_multiplier and discount.points_multiplier >= MIN_POINTS_MULTIPLIER:
        return True
    return False


def dedup(discounts: list[Discount]) -> list[Discount]:
    """依 ID 去重"""
    seen = set()
    result = []
    for d in discounts:
        if d.id not in seen:
            seen.add(d.id)
            result.append(d)
    return result


def sort_discounts(discounts: list[Discount]) -> list[Discount]:
    """
    排序：
    1. 截止日期 3 天內 → 最頂端
    2. 其餘依 value_score 由高到低
    """
    urgent = [d for d in discounts if d.urgency_days is not None and d.urgency_days <= 3]
    normal = [d for d in discounts if not (d.urgency_days is not None and d.urgency_days <= 3)]

    urgent.sort(key=lambda d: (d.urgency_days or 999, -float(d.value_score)))
    normal.sort(key=lambda d: -float(d.value_score))

    return urgent + normal


async def _run_all_scrapers() -> list[ScrapeResult]:
    """用單一 browser 同時跑所有爬蟲（節省資源）"""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
        try:
            # 每個爬蟲用獨立的 context（避免 cookie 污染）
            async def run_with_context(scrape_fn):
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="zh-TW",
                )
                page = await context.new_page()
                try:
                    result = await scrape_fn(page)
                finally:
                    await context.close()
                return result

            results = await asyncio.gather(
                run_with_context(scrape_hami),
                run_with_context(scrape_ipass),
                run_with_context(scrape_linepay),
                return_exceptions=True,
            )
        finally:
            await browser.close()

    # 過濾掉 exception
    valid = []
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"Scraper raised exception: {r}")
        else:
            valid.append(r)
    return valid


async def fetch_all_discounts(filter_high_value: bool = True) -> dict:
    """
    主要入口：爬取、篩選、排序所有平台優惠。

    返回：
    {
        "all": [...],        # 全部優惠（已排序）
        "urgent": [...],     # 截止日期 3 天內
        "errors": {...}      # 各平台爬取錯誤
    }
    """
    results = await _run_all_scrapers()

    all_discounts = []
    errors = {}

    for result in results:
        if result.error:
            errors[result.platform.value] = result.error
        all_discounts.extend(result.discounts)

    # 去重
    all_discounts = dedup(all_discounts)

    # 篩選高價值（可選）
    if filter_high_value:
        all_discounts = [d for d in all_discounts if is_high_value(d)]

    # 排序
    all_discounts = sort_discounts(all_discounts)

    urgent = [d for d in all_discounts if d.urgency_days is not None and d.urgency_days <= 3]

    return {
        "all": all_discounts,
        "urgent": urgent,
        "errors": errors,
        "total": len(all_discounts),
    }
