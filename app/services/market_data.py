from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import aiohttp

from app.config import Settings
from app.models import Candle


class MarketDataProvider(ABC):
    @abstractmethod
    async def fetch_ohlc(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        raise NotImplementedError


class TwelveDataProvider(MarketDataProvider):
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def fetch_ohlc(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        if not self.api_key:
            raise RuntimeError(
                "TWELVEDATA_API_KEY is empty. "
                "وحید: وقتی API را گرفتی، آن را در env وارد کن تا دیتای واقعی XAU/USD دریافت شود."
            )

        params = {
            "symbol": symbol,
            "interval": timeframe,
            "outputsize": str(limit),
            "apikey": self.api_key,
            "format": "JSON",
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(f"{self.base_url}/time_series", params=params) as response:
                response.raise_for_status()
                payload: dict[str, Any] = await response.json()

        values = payload.get("values")
        if not isinstance(values, list) or not values:
            message = payload.get("message") or payload.get("status") or "No data returned from market data API"
            raise RuntimeError(str(message))

        candles: list[Candle] = []
        for item in reversed(values):
            candles.append(
                Candle(
                    timestamp=datetime.fromisoformat(item["datetime"]),
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                )
            )
        return candles


def build_market_data_provider(settings: Settings) -> MarketDataProvider:
    provider = settings.market_data_provider.lower()
    if provider == "twelvedata":
        return TwelveDataProvider(
            api_key=settings.twelvedata_api_key,
            base_url=settings.twelvedata_base_url,
        )
    raise RuntimeError(f"Unsupported MARKET_DATA_PROVIDER: {settings.market_data_provider}")
