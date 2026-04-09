import hashlib
import re
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from playwright.async_api import Page

from taiwan_discounts.models.discount import Discount, Platform


class BaseScraper(ABC):
    platform: Platform

    @abstractmethod
    async def scrape(self, page: Page) -> list[Discount]:
        """爬取該平台的優惠列表"""
        ...

    def make_id(self, title: str) -> str:
        """依平台+標題產生唯一 ID"""
        raw = f"{self.platform.value}:{title}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def parse_discount_pct(self, text: str) -> Optional[Decimal]:
        """
        從文字中萃取折扣百分比。
        支援格式：
          - "10%回饋" → 10
          - "滿100折20" → 20 (20/100)
          - "8折" → 20 (= 20% off)
          - "9折" → 10
          - "半價" → 50
        """
        text = text.strip()

        # 「X倍點數」先跳過，由 parse_points_multiplier 處理
        if "倍" in text and "折" not in text:
            return None

        # 8折 / 9折 → 折扣百分比
        m = re.search(r"([0-9.]+)\s*折", text)
        if m:
            zhe = Decimal(m.group(1))
            return (1 - zhe / 10) * 100

        # X% 回饋 / 回饋X%
        m = re.search(r"([0-9.]+)\s*%", text)
        if m:
            return Decimal(m.group(1))

        # 滿N折M（例：滿100折20）
        m = re.search(r"滿\s*([0-9,]+)\s*折\s*([0-9,]+)", text)
        if m:
            base = Decimal(m.group(1).replace(",", ""))
            off = Decimal(m.group(2).replace(",", ""))
            if base > 0:
                return (off / base) * 100

        # 半價
        if "半價" in text:
            return Decimal("50")

        return None

    def parse_points_multiplier(self, text: str) -> Optional[Decimal]:
        """從文字中萃取點數倍率，例如「點數3倍」→ 3"""
        m = re.search(r"([0-9.]+)\s*倍", text)
        if m:
            try:
                return Decimal(m.group(1))
            except InvalidOperation:
                pass
        return None

    def parse_deadline(self, text: str, year: int = datetime.now().year) -> Optional[datetime]:
        """
        從文字中萃取截止日期。
        支援格式：
          - "2026/04/30"
          - "04/30"
          - "4月30日"
          - "4/30止"
        """
        text = text.strip()

        # 完整日期 YYYY/MM/DD 或 YYYY-MM-DD
        m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass

        # MM/DD 或 M月D日
        m = re.search(r"(\d{1,2})[/月](\d{1,2})[日止]?", text)
        if m:
            try:
                return datetime(year, int(m.group(1)), int(m.group(2)))
            except ValueError:
                pass

        return None
