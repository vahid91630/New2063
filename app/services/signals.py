from __future__ import annotations

from app.config import Settings
from app.models import AnalysisResult, TradePlan


class SignalBuilder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_plan(self, symbol: str, analyses: list[AnalysisResult], current_session: str) -> TradePlan:
        execution = next(item for item in analyses if item.timeframe == self.settings.execution_timeframe)
        structures = [item.structure for item in analyses]
        directional_structures = [item.structure for item in analyses if item.structure in {"Bullish", "Bearish"}]
        all_aligned = len(directional_structures) == len(analyses) and len(set(directional_structures)) == 1

        if self.settings.strict_timeframe_alignment:
            aligned = all_aligned
        else:
            higher = analyses[0]
            aligned = higher.structure == execution.structure and execution.structure in {"Bullish", "Bearish"}

        confluences = list(dict.fromkeys(sum((list(item.confluences) for item in analyses), [])))
        direction = "NO TRADE"
        entry_low = entry_high = stop_loss = tp1 = tp2 = tp3 = risk_reward = None
        probability = 0
        alternative_scenario = "Wait for clearer structure, displacement, and a valid retest."
        notes: list[str] = []

        if current_session not in self.settings.active_sessions:
            notes.append(f"Session filter blocked entries. Current session: {current_session}")

        if aligned and execution.entry_zone and len(confluences) >= self.settings.min_confluence_count and current_session in self.settings.active_sessions:
            direction = "BUY" if execution.structure == "Bullish" else "SELL"
            entry_low = execution.entry_zone.low
            entry_high = execution.entry_zone.high
            stop_buffer = max(abs(entry_high - entry_low) * 0.20, 0.10)

            if direction == "BUY":
                stop_loss = (execution.invalidation or entry_low) - stop_buffer
                risk = ((entry_low + entry_high) / 2) - stop_loss
                tp1 = execution.dealing_range_high
                tp2 = execution.dealing_range_high + risk
                tp3 = execution.dealing_range_high + (risk * 2)
            else:
                stop_loss = (execution.invalidation or entry_high) + stop_buffer
                risk = stop_loss - ((entry_low + entry_high) / 2)
                tp1 = execution.dealing_range_low
                tp2 = execution.dealing_range_low - risk
                tp3 = execution.dealing_range_low - (risk * 2)

            if risk > 0 and tp1 is not None:
                entry_mid = (entry_low + entry_high) / 2
                first_reward = abs(tp1 - entry_mid)
                risk_reward = round(first_reward / risk, 2)

            probability = min(90, 45 + (len(confluences) * 6) + (2 if all_aligned else 0))
            alternative_scenario = self._build_invalidation_text(direction, stop_loss)
        else:
            if not aligned:
                notes.append(f"Timeframe alignment failed: {', '.join(structures)}")
            if len(confluences) < self.settings.min_confluence_count:
                notes.append("Confluence count is below the required threshold.")
            if not execution.entry_zone:
                notes.append("No execution-quality entry zone was found.")

        market_structure_text = self._build_market_structure_text(analyses)
        liquidity_text = self._build_liquidity_text(execution)
        smart_money_zones_text = self._build_zones_text(execution)
        quality_score = min(10.0, round((len(confluences) * 1.5) + (1.0 if all_aligned else 0.0), 1))

        return TradePlan(
            symbol=symbol,
            timeframe=execution.timeframe,
            direction=direction,
            entry_low=entry_low,
            entry_high=entry_high,
            stop_loss=stop_loss,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            risk_reward=risk_reward,
            probability=probability,
            market_structure_text=market_structure_text,
            liquidity_analysis_text=liquidity_text,
            smart_money_zones_text=smart_money_zones_text,
            alternative_scenario=alternative_scenario,
            trade_quality_score=quality_score,
            confluences=confluences,
            analysis_notes=notes,
        )

    def build_no_trade_summary(self, analyses: list[AnalysisResult], current_session: str) -> tuple[list[str], list[str]]:
        reasons: list[str] = [f"Current session: {current_session}"]

        structures = [f"{item.timeframe}={item.structure}" for item in analyses]
        if self.settings.strict_timeframe_alignment:
            if len({item.structure for item in analyses}) != 1:
                reasons.append("Strict timeframe alignment not satisfied.")

        execution = next(item for item in analyses if item.timeframe == self.settings.execution_timeframe)
        if not execution.entry_zone:
            reasons.append("No valid execution entry zone.")
        if len(execution.confluences) < self.settings.min_confluence_count:
            reasons.append("Execution timeframe confluence is below threshold.")
        if current_session not in self.settings.active_sessions:
            reasons.append("Current session is outside allowed trading sessions.")

        return reasons, structures

    def _build_market_structure_text(self, analyses: list[AnalysisResult]) -> str:
        parts = []
        for item in analyses:
            parts.append(
                f"{item.timeframe}: {item.structure} | BOS={'; '.join(item.bos) or 'none'} | "
                f"CHoCH={'; '.join(item.choch) or 'none'} | intention={item.smart_money_intention}"
            )
        return "\n".join(parts)

    def _build_liquidity_text(self, item: AnalysisResult) -> str:
        return (
            f"Sweeps: {', '.join(item.liquidity_sweeps) or 'none'}\n"
            f"Internal liquidity: {', '.join(item.internal_liquidity) or 'none'}\n"
            f"External liquidity: {', '.join(item.external_liquidity) or 'none'}\n"
            f"EQH: {', '.join(item.equal_highs) or 'none'}\n"
            f"EQL: {', '.join(item.equal_lows) or 'none'}"
        )

    def _build_zones_text(self, item: AnalysisResult) -> str:
        def fmt(zone: object) -> str:
            if zone is None:
                return "none"
            if isinstance(zone, list):
                if not zone:
                    return "none"
                return "; ".join(f"{z.label} [{z.low:.2f}-{z.high:.2f}]" for z in zone)
            return f"{zone.label} [{zone.low:.2f}-{zone.high:.2f}]"

        return (
            f"Order Block: {fmt(item.order_blocks)}\n"
            f"FVG: {fmt(item.fvgs)}\n"
            f"Breaker: {fmt(item.breaker_blocks)}\n"
            f"Mitigation: {fmt(item.mitigation_blocks)}\n"
            f"Premium/Discount: premium={fmt(item.premium_zone)} | discount={fmt(item.discount_zone)}"
        )

    def _build_invalidation_text(self, direction: str, stop_loss: float | None) -> str:
        if stop_loss is None:
            return "Setup invalidates on loss of structure."
        if direction == "BUY":
            return f"Invalid if price closes below {stop_loss:.2f} on the execution timeframe."
        return f"Invalid if price closes above {stop_loss:.2f} on the execution timeframe."
