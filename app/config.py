from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Tuple

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    port: int
    account_balance: float
    risk_percent: float
    symbol: str
    top_down_timeframes: Tuple[str, ...]
    execution_timeframe: str
    poll_interval_seconds: int
    bars_limit: int
    min_confluence_count: int
    min_signal_interval_minutes: int
    market_data_provider: str
    twelvedata_api_key: str
    twelvedata_base_url: str
    strict_timeframe_alignment: bool
    send_no_trade_updates: bool
    active_sessions: Tuple[str, ...]
    session_timezone: str


def _get_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _csv_to_tuple(value: str) -> Tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _bool_env(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    return Settings(
        telegram_bot_token=_get_required("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_get_required("TELEGRAM_CHAT_ID"),
        port=int(os.getenv("PORT", "8080")),
        account_balance=float(os.getenv("ACCOUNT_BALANCE", "10000")),
        risk_percent=float(os.getenv("RISK_PERCENT", "1")),
        symbol=os.getenv("SYMBOL", "XAU/USD").strip() or "XAU/USD",
        top_down_timeframes=_csv_to_tuple(os.getenv("TOP_DOWN_TIMEFRAMES", "4h,1h,15min")),
        execution_timeframe=os.getenv("EXECUTION_TIMEFRAME", "15min").strip() or "15min",
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "900")),
        bars_limit=int(os.getenv("BARS_LIMIT", "500")),
        min_confluence_count=int(os.getenv("MIN_CONFLUENCE_COUNT", "3")),
        min_signal_interval_minutes=int(os.getenv("MIN_SIGNAL_INTERVAL_MINUTES", "30")),
        market_data_provider=os.getenv("MARKET_DATA_PROVIDER", "twelvedata").strip().lower() or "twelvedata",
        twelvedata_api_key=os.getenv("TWELVEDATA_API_KEY", "").strip(),
        twelvedata_base_url=os.getenv("TWELVEDATA_BASE_URL", "https://api.twelvedata.com").strip()
        or "https://api.twelvedata.com",
        strict_timeframe_alignment=_bool_env("STRICT_TIMEFRAME_ALIGNMENT", "true"),
        send_no_trade_updates=_bool_env("SEND_NO_TRADE_UPDATES", "false"),
        active_sessions=_csv_to_tuple(os.getenv("ACTIVE_SESSIONS", "london,newyork")),
        session_timezone=os.getenv("SESSION_TIMEZONE", "UTC").strip() or "UTC",
    )
