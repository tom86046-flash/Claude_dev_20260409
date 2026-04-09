"""
Line Pay 台灣爬蟲
目標：https://event-pay.line.me/tw/
"""
import logging
from playwright.async_api import Page

from taiwan_discounts.models.discount import Discount, DiscountCategory, Platform, ScrapeResult
from taiwan_discounts.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

CATEGORY_KEYWORDS = {
    DiscountCategory.FOOD_DRINK: ["餐廳", "餐飲", "麥當勞", "肯德基", "飲料", "咖啡", "美食", "foodpanda", "uber eats"],
    DiscountCategory.CONVENIENCE: ["全家", "7-eleven", "711", "萊爾富", "超商", "全聯", "家樂福"],
    DiscountCategory.TRANSPORT: ["捷運", "台灣好行", "uber", "計程車", "交通"],
    DiscountCategory.FUEL: ["加油", "台塑", "中油"],
    DiscountCategory.SHOPPING: ["購物", "百貨", "momo", "蝦皮", "shopee"],
    DiscountCategory.ENTERTAINMENT: ["電影", "ktv", "娛樂"],
    DiscountCategory.UTILITIES: ["繳費", "電費"],
}


def guess_category(text: str) -> DiscountCategory:
    text_lower = text.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return cat
    return DiscountCategory.OTHER


class LinePayScraper(BaseScraper):
    platform = Platform.LINE_PAY
    url = "https://event-pay.line.me/tw/"

    async def scrape(self, page: Page) -> list[Discount]:
        try:
            return await self._scrape_page(page)
        except Exception as e:
            logger.warning(f"Line Pay scrape failed: {e}")
            return []

    async def _scrape_page(self, page: Page) -> list[Discount]:
        await page.goto(self.url, wait_until="networkidle", timeout=30000)

        # Line Pay 頁面可能需要滾動才能載入全部內容
        for _ in range(3):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)

        # event-pay.line.me/tw/ 的實際結構
        selectors = [
            ".event-list__item",
            ".event-item",
            ".promotion-item",
            ".campaign-card",
            "[class*='eventList'] li",
            "[class*='event-list'] li",
            "[class*='EventList'] li",
            "[class*='promotion']",
            "[class*='campaign']",
            "article",
            "li.item",
        ]

        cards = []
        for sel in selectors:
            cards = await page.query_selector_all(sel)
            if len(cards) > 1:
                break

        if not cards:
            return await self._fallback_parse(page)

        discounts = []
        for card in cards:
            try:
                discount = await self._parse_card(card)
                if discount:
                    discounts.append(discount)
            except Exception as e:
                logger.debug(f"Line Pay card parse error: {e}")

        return discounts

    async def _parse_card(self, card) -> Discount | None:
        title_el = await card.query_selector("h2, h3, h4, .title, [class*='title'], strong")
        title = (await title_el.inner_text()).strip() if title_el else ""
        if not title:
            return None

        desc_el = await card.query_selector(".desc, .description, p, [class*='desc']")
        desc_text = (await desc_el.inner_text()).strip() if desc_el else ""

        date_el = await card.query_selector(".date, .deadline, time, [class*='date'], [class*='period']")
        date_text = (await date_el.inner_text()).strip() if date_el else ""
        deadline = self.parse_deadline(date_text) if date_text else None

        link_el = await card.query_selector("a")
        href = await link_el.get_attribute("href") if link_el else None
        if href and not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin(self.url, href)
        url = href or self.url

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

    async def _fallback_parse(self, page: Page) -> list[Discount]:
        try:
            text = await page.inner_text("body")
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            discounts = []
            for line in lines:
                if any(kw in line for kw in ["回饋", "折", "%", "倍", "優惠", "LINE Points"]) and len(line) < 150:
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
                            url=self.url,
                        ))
            return discounts[:20]
        except Exception as e:
            logger.warning(f"Line Pay fallback parse failed: {e}")
            return []


async def scrape_linepay(page: Page) -> ScrapeResult:
    scraper = LinePayScraper()
    try:
        discounts = await scraper.scrape(page)
        return ScrapeResult(platform=Platform.LINE_PAY, discounts=discounts)
    except Exception as e:
        logger.error(f"Line Pay scrape error: {e}")
        return ScrapeResult(platform=Platform.LINE_PAY, discounts=[], error=str(e))
