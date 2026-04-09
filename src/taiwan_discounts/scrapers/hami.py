"""
Hami Point 爬蟲
目標：https://hamipoint.cht.com.tw/promotion
"""
import logging
from playwright.async_api import Page

from taiwan_discounts.models.discount import Discount, DiscountCategory, Platform, ScrapeResult
from taiwan_discounts.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# 類別關鍵字對應
CATEGORY_KEYWORDS = {
    DiscountCategory.FOOD_DRINK: ["餐廳", "餐飲", "麥當勞", "肯德基", "飲料", "咖啡", "pizza", "美食"],
    DiscountCategory.CONVENIENCE: ["全家", "7-eleven", "711", "萊爾富", "ok mart", "超商", "全聯", "家樂福", "超市"],
    DiscountCategory.TRANSPORT: ["捷運", "公車", "台鐵", "高鐵", "uber", "計程車", "加油"],
    DiscountCategory.FUEL: ["加油", "台塑", "中油", "全國"],
    DiscountCategory.SHOPPING: ["momo", "pchome", "shopee", "蝦皮", "購物", "百貨"],
    DiscountCategory.ENTERTAINMENT: ["電影", "ktv", "遊樂", "票券"],
    DiscountCategory.UTILITIES: ["繳費", "電費", "水費", "瓦斯"],
}


def guess_category(text: str) -> DiscountCategory:
    text_lower = text.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return cat
    return DiscountCategory.OTHER


class HamiScraper(BaseScraper):
    platform = Platform.HAMI_POINT
    urls = [
        "https://hamipoint.cht.com.tw/promotion",
        "https://hamipay.cht.com.tw/promotions.html",
    ]

    async def scrape(self, page: Page) -> list[Discount]:
        discounts = []
        for url in self.urls:
            try:
                discounts.extend(await self._scrape_page(page, url))
            except Exception as e:
                logger.warning(f"Hami scrape failed for {url}: {e}")
        return discounts

    async def _scrape_page(self, page: Page, url: str) -> list[Discount]:
        # 攔截 API 回應（hamipoint.cht.com.tw 是 Vue SPA，資料來自 XHR）
        api_discounts = []

        async def handle_response(response):
            if response.status == 200 and any(
                kw in response.url for kw in ["/promotion", "/activity", "/campaign", "/api/"]
            ):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        data = await response.json()
                        extracted = self._parse_api_response(data, url)
                        api_discounts.extend(extracted)
                except Exception:
                    pass

        page.on("response", handle_response)
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        if api_discounts:
            logger.info(f"Hami API 攔截到 {len(api_discounts)} 筆")
            return api_discounts

        # 等待優惠卡片載入（hamipoint.cht.com.tw/promotion 的實際結構）
        selectors = [
            "li.promotion-list__item",
            ".promotion-item",
            ".promotion-card",
            "li[class*='promotion']",
            "li[class*='promo']",
            ".campaign-item",
            ".activity-card",
            "article",
            "li.item",
        ]

        cards = []
        for sel in selectors:
            cards = await page.query_selector_all(sel)
            if cards:
                break

        if not cards:
            # fallback：嘗試抓所有含有折扣關鍵字的區塊
            logger.info(f"Hami: no cards found with standard selectors at {url}, trying fallback")
            return await self._fallback_parse(page, url)

        discounts = []
        for card in cards:
            try:
                discount = await self._parse_card(card, url)
                if discount:
                    discounts.append(discount)
            except Exception as e:
                logger.debug(f"Hami card parse error: {e}")

        return discounts

    def _parse_api_response(self, data, base_url: str) -> list[Discount]:
        """嘗試從 JSON API 回應萃取優惠"""
        items = []
        # 嘗試常見的 JSON 結構
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ["data", "list", "items", "promotions", "activities", "result"]:
                if isinstance(data.get(key), list):
                    items = data[key]
                    break

        discounts = []
        for item in items[:30]:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("name") or item.get("promotionName") or ""
            if not title:
                continue
            desc = item.get("description") or item.get("content") or item.get("subtitle") or title
            url = item.get("url") or item.get("link") or base_url
            deadline_str = (
                item.get("endDate") or item.get("end_date") or
                item.get("endTime") or item.get("deadline") or ""
            )
            deadline = self.parse_deadline(str(deadline_str)) if deadline_str else None
            combined = f"{title} {desc}"
            discounts.append(Discount(
                id=self.make_id(title),
                title=str(title),
                platform=self.platform,
                discount_amount=str(desc)[:100],
                discount_value_pct=self.parse_discount_pct(combined),
                points_multiplier=self.parse_points_multiplier(combined),
                deadline=deadline,
                category=guess_category(combined),
                conditions=[],
                url=str(url),
            ))
        return discounts

    async def _parse_card(self, card, base_url: str) -> Discount | None:
        # 標題
        title_el = await card.query_selector("h2, h3, .title, .name, [class*='title']")
        title = (await title_el.inner_text()).strip() if title_el else ""
        if not title:
            return None

        # 折扣描述
        desc_el = await card.query_selector(".desc, .description, .discount, [class*='desc'], p")
        desc_text = (await desc_el.inner_text()).strip() if desc_el else ""

        # 截止日期
        date_el = await card.query_selector(".date, .deadline, .end-date, [class*='date'], time")
        date_text = (await date_el.inner_text()).strip() if date_el else ""
        deadline = self.parse_deadline(date_text) if date_text else None

        # 連結
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
        """當找不到標準卡片結構時，嘗試從頁面文字粗略萃取優惠"""
        try:
            text = await page.inner_text("body")
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            discounts = []
            for i, line in enumerate(lines):
                # 找含有折扣關鍵字的行
                if any(kw in line for kw in ["回饋", "折", "%", "倍點", "優惠"]) and len(line) < 100:
                    title = line
                    desc = lines[i + 1] if i + 1 < len(lines) else ""
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
            return discounts[:20]  # 限制數量
        except Exception as e:
            logger.warning(f"Hami fallback parse failed: {e}")
            return []


async def scrape_hami(page: Page) -> ScrapeResult:
    scraper = HamiScraper()
    try:
        discounts = await scraper.scrape(page)
        return ScrapeResult(platform=Platform.HAMI_POINT, discounts=discounts)
    except Exception as e:
        logger.error(f"Hami scrape error: {e}")
        return ScrapeResult(platform=Platform.HAMI_POINT, discounts=[], error=str(e))
