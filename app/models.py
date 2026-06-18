from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Sequence


Direction = Literal["BUY", "SELL", "NO TRADE"]
StructureState = Literal["Bullish", "Bearish", "Range"]


@dataclass(frozen=True, slots=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class PriceZone:
    low: float
    high: float
    label: str

    def midpoint(self) -> float:
        return (self.low + self.high) / 2


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    timeframe: str
    structure: StructureState
    bos: list[str]
    choch: list[str]
    liquidity_sweeps: list[str]
    internal_liquidity: list[str]
    external_liquidity: list[str]
    equal_highs: list[str]
    equal_lows: list[str]
    order_blocks: list[PriceZone]
    breaker_blocks: list[PriceZone]
    mitigation_blocks: list[PriceZone]
    fvgs: list[PriceZone]
    inversion_fvgs: list[PriceZone]
    premium_zone: PriceZone | None
    discount_zone: PriceZone | None
    smart_money_intention: str
    likely_path: str
    entry_zone: PriceZone | None
    invalidation: float | None
    confluences: list[str]
    current_price: float
    dealing_range_low: float
    dealing_range_high: float


@dataclass(frozen=True, slots=True)
class TradePlan:
    symbol: str
    timeframe: str
    direction: Direction
    entry_low: float | None
    entry_high: float | None
    stop_loss: float | None
    take_profit_1: float | None
    take_profit_2: float | None
    take_profit_3: float | None
    risk_reward: float | None
    probability: int
    market_structure_text: str
    liquidity_analysis_text: str
    smart_money_zones_text: str
    alternative_scenario: str
    trade_quality_score: float
    confluences: Sequence[str] = field(default_factory=tuple)
    analysis_notes: Sequence[str] = field(default_factory=tuple)

    @property
    def is_trade(self) -> bool:
        return self.direction in {"BUY", "SELL"} and self.entry_low is not None and self.entry_high is not None
