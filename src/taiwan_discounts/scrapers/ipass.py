"""
iPASS 悠游付爬蟲
目標：https://www.ipass.com.tw/活動優惠 及相關頁面
"""
import logging
from playwright.async_api import Page

from taiwan_discounts.models.discount import Discount, DiscountCategory, Platform, ScrapeResult
from taiwan_discounts.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

CATEGORY_KEYWORDS = {
    DiscountCategory.FOOD_DRINK: ["餐廳", "餐飲", "飲料", "咖啡", "美食"],
    DiscountCategory.CONVENIENCE: ["全家", "7-eleven", "711", "萊爾富", "超商", "全聯", "超市"],
    DiscountCategory.TRANSPORT: ["捷運", "公車", "台鐵", "高鐵", "交通"],
    DiscountCategory.FUEL: ["加油", "台塑", "中油"],
    DiscountCategory.SHOPPING: ["購物", "百貨", "momo", "蝦皮"],
    DiscountCategory.ENTERTAINMENT: ["電影", "ktv", "娛樂"],
    DiscountCategory.UTILITIES: ["繳費", "電費"],
}


def guess_category(text: str) -> DiscountCategory:
    text_lower = text.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return cat
    return DiscountCategory.OTHER


class IpassScraper(BaseScraper):
    platform = Platform.IPASS
    urls = [
        "https://www.ipass.com.tw/活動優惠/",
        "https://www.ipass.com.tw/campaign/",
    ]

    async def scrape(self, page: Page) -> list[Discount]:
        discounts = []
        for url in self.urls:
            try:
                discounts.extend(await self._scrape_page(page, url))
            except Exception as e:
                logger.warning(f"iPASS scrape failed for {url}: {e}")
        return discounts

    async def _scrape_page(self, page: Page, url: str) -> list[Discount]:
        await page.goto(url, wait_until="networkidle", timeout=30000)

        # 嘗試多種 selector
        selectors = [
            ".campaign-item",
            ".activity-item",
            ".promo-item",
            ".event-card",
            ".card",
            "article",
            "li.item",
        ]

        cards = []
        for sel in selectors:
            cards = await page.query_selector_all(sel)
            if len(cards) > 2:
                break

        if not cards:
            return await self._fallback_parse(page, url)

        discounts = []
        for card in cards:
            try:
                discount = await self._parse_card(card, url)
                if discount:
                    discounts.append(discount)
            except Exception as e:
                logger.debug(f"iPASS card parse error: {e}")

        return discounts

    async def _parse_card(self, card, base_url: str) -> Discount | None:
        title_el = await card.query_selector("h2, h3, h4, .title, .name, [class*='title']")
        title = (await title_el.inner_text()).strip() if title_el else ""
        if not title:
            return None

        desc_el = await card.query_selector(".desc, .description, p, [class*='desc']")
        desc_text = (await desc_el.inner_text()).strip() if desc_el else ""

        date_el = await card.query_selector(".date, .deadline, time, [class*='date']")
        date_text = (await date_el.inner_text()).strip() if date_el else ""
        deadline = self.parse_deadline(date_text) if date_text else None

        link_el = await card.query_selector("a")
        href = await link_el.get_attribute("href") if link_el else None
        if href and not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin(base_url, href)
        url = href or base_url

        combined_text = f"{title} {desc_text}"
        discount_pct = self.parse_discount_pct(combined_text)
        points_mult = self.parse_points_multiplier(combined_text)

        return Discount(
            id=self.make_id(title),
            title=title,
            platform=self.platform,
            discount_amount=desc_text or title,
            discount_value_pct=discount_pct,
            points_multiplier=points_mult,
            deadline=deadline,
            category=guess_category(combined_text),
            conditions=[],
            url=url,
        )

    async def _fallback_parse(self, page: Page, url: str) -> list[Discount]:
        try:
            text = await page.inner_text("body")
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            discounts = []
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["回饋", "折", "%", "倍點", "優惠"]) and len(line) < 100:
                    title = line
                    discount_pct = self.parse_discount_pct(title)
                    points_mult = self.parse_points_multiplier(title)
                    if discount_pct or points_mult:
                        discounts.append(Discount(
                            id=self.make_id(title),
                            title=title,
                            platform=self.platform,
                            discount_amount=title,
                            discount_value_pct=discount_pct,
                            points_multiplier=points_mult,
                            deadline=None,
                            category=guess_category(title),
                            conditions=[],
                            url=url,
                        ))
            return discounts[:20]
        except Exception as e:
            logger.warning(f"iPASS fallback parse failed: {e}")
            return []


async def scrape_ipass(page: Page) -> ScrapeResult:
    scraper = IpassScraper()
    try:
        discounts = await scraper.scrape(page)
        return ScrapeResult(platform=Platform.IPASS, discounts=discounts)
    except Exception as e:
        logger.error(f"iPASS scrape error: {e}")
        return ScrapeResult(platform=Platform.IPASS, discounts=[], error=str(e))
