from __future__ import annotations

import logging

from telegram import Bot
from telegram.error import TelegramError

from app.config import Settings
from app.models import TradePlan

LOGGER = logging.getLogger(__name__)
MAX_MESSAGE_LENGTH = 4000


class TelegramNotifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bot = Bot(token=settings.telegram_bot_token)

    async def send_message(self, text: str) -> bool:
        chunks = self._chunk_text(text)
        try:
            for chunk in chunks:
                await self.bot.send_message(
                    chat_id=self.settings.telegram_chat_id,
                    text=chunk,
                    disable_web_page_preview=True,
                )
            return True
        except TelegramError as exc:
            LOGGER.exception("Telegram send_message failed: %s", exc)
            return False
        except Exception as exc:
            LOGGER.exception("Unexpected telegram error: %s", exc)
            return False

    async def send_plan(self, plan: TradePlan, risk_lines: str) -> bool:
        lines = [
            f"XAUUSD Signal Bot | {plan.timeframe}",
            "",
            "MARKET STRUCTURE:",
            plan.market_structure_text,
            "",
            "LIQUIDITY ANALYSIS:",
            plan.liquidity_analysis_text,
            "",
            "SMART MONEY ZONES:",
            plan.smart_money_zones_text,
            "",
            "TRADE SETUP:",
            f"- Direction: {plan.direction}",
            f"- Entry: {self._zone(plan.entry_low, plan.entry_high)}",
            f"- Stop Loss: {self._price(plan.stop_loss)}",
            f"- TP1: {self._price(plan.take_profit_1)}",
            f"- TP2: {self._price(plan.take_profit_2)}",
            f"- TP3: {self._price(plan.take_profit_3)}",
            f"- R:R: {plan.risk_reward if plan.risk_reward is not None else 'n/a'}",
            f"- Probability: {plan.probability}%",
            "",
            "ALTERNATIVE SCENARIO:",
            plan.alternative_scenario,
            "",
            "RISK MANAGEMENT:",
            risk_lines,
            "",
            f"TRADE QUALITY SCORE:\n{plan.trade_quality_score}/10",
            "",
            f"FINAL DECISION:\n{plan.direction}",
        ]

        if plan.confluences:
            lines.extend(["", "CONFLUENCES:", *[f"- {item}" for item in plan.confluences]])

        if plan.analysis_notes:
            lines.extend(["", "NOTES:", *[f"- {item}" for item in plan.analysis_notes]])

        return await self.send_message("\n".join(lines))

    async def send_no_trade_update(
        self,
        symbol: str,
        timeframe: str,
        reason_lines: list[str],
        structure_lines: list[str],
    ) -> bool:
        text = "\n".join(
            [
                f"{symbol} | {timeframe}",
                "",
                "FINAL DECISION:",
                "NO TRADE",
                "",
                "WAIT FOR CONFIRMATION",
                "",
                "WHY:",
                *[f"- {line}" for line in reason_lines],
                "",
                "STRUCTURE SNAPSHOT:",
                *[f"- {line}" for line in structure_lines],
            ]
        )
        return await self.send_message(text)

    def _price(self, value: float | None) -> str:
        return "n/a" if value is None else f"{value:.2f}"

    def _zone(self, low: float | None, high: float | None) -> str:
        if low is None or high is None:
            return "n/a"
        return f"{low:.2f} - {high:.2f}"

    def _chunk_text(self, text: str) -> list[str]:
        if len(text) <= MAX_MESSAGE_LENGTH:
            return [text]

        chunks: list[str] = []
        current = []
        current_len = 0

        for line in text.splitlines(True):
            if current_len + len(line) > MAX_MESSAGE_LENGTH:
                chunks.append("".join(current).rstrip())
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += len(line)

        if current:
            chunks.append("".join(current).rstrip())
        return chunks
