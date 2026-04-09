from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, HttpUrl


class Platform(str, Enum):
    HAMI_POINT = "Hami Point"
    IPASS = "iPASS 悠游付"
    LINE_PAY = "Line Pay"


class DiscountCategory(str, Enum):
    FOOD_DRINK = "餐飲"
    CONVENIENCE = "超商/超市"
    TRANSPORT = "交通"
    SHOPPING = "購物"
    ENTERTAINMENT = "娛樂"
    UTILITIES = "繳費"
    FUEL = "加油"
    OTHER = "其他"


class Discount(BaseModel):
    id: str                                      # platform + title hash，用來去重
    title: str                                   # 優惠標題
    platform: Platform
    discount_amount: str                         # 人類可讀描述，例如「10%回饋」
    discount_value_pct: Optional[Decimal] = None # 數字化折扣 %，用來排序和篩選
    points_multiplier: Optional[Decimal] = None  # 點數倍率（若為點數活動）
    deadline: Optional[datetime] = None          # 截止日期
    category: DiscountCategory = DiscountCategory.OTHER
    conditions: list[str] = []                  # 使用條件
    url: str                                     # 優惠連結
    urgency_days: Optional[int] = None           # 距截止幾天（自動計算）
    value_score: Decimal = Decimal("0")          # 綜合評分，用來排名

    def model_post_init(self, __context) -> None:
        # 計算截止幾天
        if self.deadline:
            now = datetime.now(timezone.utc)
            deadline = self.deadline
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            delta = deadline - now
            self.urgency_days = max(0, delta.days)

        # 計算綜合評分
        score = Decimal("0")
        if self.discount_value_pct:
            score += self.discount_value_pct
        if self.points_multiplier:
            # 點數倍率換算成等效折扣分數
            score += (self.points_multiplier - 1) * 5
        # 快到期加分（製造緊迫感）
        if self.urgency_days is not None and self.urgency_days <= 3:
            score += Decimal("10")
        self.value_score = score


class ScrapeResult(BaseModel):
    platform: Platform
    discounts: list[Discount]
    error: Optional[str] = None
    scraped_at: datetime = datetime.now(timezone.utc)
