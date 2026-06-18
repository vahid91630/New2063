from __future__ import annotations

from telegram import Bot

from app.config import Settings
from app.models import TradePlan


class TelegramNotifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bot = Bot(token=settings.telegram_bot_token)

    async def send_message(self, text: str) -> None:
        await self.bot.send_message(
            chat_id=self.settings.telegram_chat_id,
            text=text,
            disable_web_page_preview=True,
        )

    async def send_plan(self, plan: TradePlan, risk_lines: str) -> None:
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

        await self.send_message("\n".join(lines))

    def _price(self, value: float | None) -> str:
        return "n/a" if value is None else f"{value:.2f}"

    def _zone(self, low: float | None, high: float | None) -> str:
        if low is None or high is None:
            return "n/a"
        return f"{low:.2f} - {high:.2f}"
