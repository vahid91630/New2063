from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import Settings
from app.models import TradePlan
from app.services.analysis import SMCAnalyzer
from app.services.market_data import build_market_data_provider
from app.services.signals import SignalBuilder
from app.services.telegram_notifier import TelegramNotifier

LOGGER = logging.getLogger(__name__)
STATE_FILE = Path("runtime_state.json")


class TradingBotRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = build_market_data_provider(settings)
        self.analyzer = SMCAnalyzer()
        self.signal_builder = SignalBuilder(settings)
        self.notifier = TelegramNotifier(settings)

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        startup_sent = await self.notifier.send_message(
            "XAUUSD signal engine started. Waiting for top-down confluence."
        )
        if not startup_sent:
            LOGGER.warning("Startup telegram message failed. Bot will continue running.")

        while not stop_event.is_set():
            try:
                analyses = await self._build_analyses()
                current_session = self.analyzer.session_label(datetime.now(UTC))
                plan = self.signal_builder.build_plan(
                    symbol=self.settings.symbol,
                    analyses=analyses,
                    current_session=current_session,
                )

                if await self._should_send(plan):
                    risk_lines = self._build_risk_lines(plan)
                    sent = await self.notifier.send_plan(plan, risk_lines)
                    if sent:
                        self._save_state(plan)
                    else:
                        LOGGER.warning("Trade plan was generated but telegram delivery failed.")
                else:
                    LOGGER.info("No new signal sent.")
                    if self.settings.send_no_trade_updates:
                        reasons, structures = self.signal_builder.build_no_trade_summary(analyses, current_session)
                        await self.notifier.send_no_trade_update(
                            symbol=self.settings.symbol,
                            timeframe=self.settings.execution_timeframe,
                            reason_lines=reasons,
                            structure_lines=structures,
                        )
            except Exception as exc:
                LOGGER.exception("Signal cycle failed: %s", exc)
                await self.notifier.send_message(f"Signal cycle failed: {exc}")

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.settings.poll_interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def _build_analyses(self) -> list:
        analyses = []
        for timeframe in self.settings.top_down_timeframes:
            candles = await self.provider.fetch_ohlc(
                symbol=self.settings.symbol,
                timeframe=timeframe,
                limit=self.settings.bars_limit,
            )
            analyses.append(self.analyzer.analyze(timeframe=timeframe, candles=candles))
        return analyses

    async def _should_send(self, plan: TradePlan) -> bool:
        if not plan.is_trade:
            return False

        state = self._load_state()
        if not state:
            return True

        last_time_str = state.get("last_sent_at")
        last_direction = state.get("direction")
        last_entry_low = state.get("entry_low")
        last_entry_high = state.get("entry_high")

        if last_time_str:
            last_time = datetime.fromisoformat(last_time_str)
            min_gap = timedelta(minutes=self.settings.min_signal_interval_minutes)
            if datetime.now(UTC) - last_time < min_gap:
                if (
                    last_direction == plan.direction
                    and round(float(last_entry_low or 0), 2) == round(float(plan.entry_low or 0), 2)
                    and round(float(last_entry_high or 0), 2) == round(float(plan.entry_high or 0), 2)
                ):
                    return False
        return True

    def _build_risk_lines(self, plan: TradePlan) -> str:
        if not plan.is_trade or plan.stop_loss is None or plan.entry_low is None or plan.entry_high is None:
            capital_at_risk = self.settings.account_balance * (self.settings.risk_percent / 100)
            return (
                f"- Risk = {self.settings.risk_percent}%\n"
                f"- Position Size Formula: capital_at_risk / stop_loss_distance\n"
                f"- Capital at Risk: {capital_at_risk:.2f}"
            )

        entry_mid = (plan.entry_low + plan.entry_high) / 2
        stop_loss_distance = abs(entry_mid - plan.stop_loss)
        capital_at_risk = self.settings.account_balance * (self.settings.risk_percent / 100)
        position_size = capital_at_risk / stop_loss_distance if stop_loss_distance else 0.0

        return (
            f"- Risk = {self.settings.risk_percent}%\n"
            f"- Stop Loss Distance: {stop_loss_distance:.2f}\n"
            f"- Position Size Formula: ({self.settings.account_balance:.2f} x {self.settings.risk_percent / 100:.4f}) / {stop_loss_distance:.2f}\n"
            f"- Position Size: {position_size:.4f} units\n"
            f"- Lot Size Formula: capital_at_risk / (stop_loss_distance x contract_value_per_point)\n"
            f"- Capital at Risk: {capital_at_risk:.2f}"
        )

    def _load_state(self) -> dict[str, object]:
        if not STATE_FILE.exists():
            return {}
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))

    def _save_state(self, plan: TradePlan) -> None:
        payload = {
            "last_sent_at": datetime.now(UTC).isoformat(),
            "direction": plan.direction,
            "entry_low": plan.entry_low,
            "entry_high": plan.entry_high,
        }
        STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
