from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.models import AnalysisResult, Candle, PriceZone


@dataclass(frozen=True, slots=True)
class SwingPoint:
    index: int
    price: float
    kind: str


class SMCAnalyzer:
    def __init__(self, swing_window: int = 3) -> None:
        self.swing_window = swing_window

    def analyze(self, timeframe: str, candles: list[Candle]) -> AnalysisResult:
        if len(candles) < 40:
            raise RuntimeError("Not enough candles for analysis. Increase BARS_LIMIT.")

        highs = self._find_swings(candles, kind="high")
        lows = self._find_swings(candles, kind="low")
        structure = self._determine_structure(highs, lows)
        bos, choch = self._detect_bos_choch(candles, highs, lows, structure)
        eqh, eql = self._find_equal_levels(highs, lows, candles)
        sweeps = self._find_liquidity_sweeps(candles, eqh, eql)
        internal_liquidity, external_liquidity = self._classify_liquidity(highs, lows, candles)
        fvgs, inversion_fvgs = self._find_fvgs(candles)
        order_blocks = self._find_order_blocks(candles)
        breaker_blocks = self._find_breaker_blocks(candles, order_blocks)
        mitigation_blocks = self._find_mitigation_blocks(candles, order_blocks)
        premium_zone, discount_zone, range_low, range_high = self._find_dealing_range(candles)
        current_price = candles[-1].close
        entry_zone, invalidation, intention, likely_path, confluences = self._build_narrative(
            structure=structure,
            current_price=current_price,
            sweeps=sweeps,
            order_blocks=order_blocks,
            fvgs=fvgs,
            premium_zone=premium_zone,
            discount_zone=discount_zone,
            range_low=range_low,
            range_high=range_high,
            bos=bos,
            choch=choch,
        )

        return AnalysisResult(
            timeframe=timeframe,
            structure=structure,
            bos=bos,
            choch=choch,
            liquidity_sweeps=sweeps,
            internal_liquidity=internal_liquidity,
            external_liquidity=external_liquidity,
            equal_highs=eqh,
            equal_lows=eql,
            order_blocks=order_blocks,
            breaker_blocks=breaker_blocks,
            mitigation_blocks=mitigation_blocks,
            fvgs=fvgs,
            inversion_fvgs=inversion_fvgs,
            premium_zone=premium_zone,
            discount_zone=discount_zone,
            smart_money_intention=intention,
            likely_path=likely_path,
            entry_zone=entry_zone,
            invalidation=invalidation,
            confluences=confluences,
            current_price=current_price,
            dealing_range_low=range_low,
            dealing_range_high=range_high,
        )

    def session_label(self, when: datetime | None = None) -> str:
        now = when or datetime.now(UTC)
        hour = now.hour

        if 7 <= hour < 11:
            return "london"
        if 12 <= hour < 17:
            return "newyork"
        if 0 <= hour < 5:
            return "asia"
        return "off_session"

    def _find_swings(self, candles: list[Candle], kind: str) -> list[SwingPoint]:
        points: list[SwingPoint] = []
        for i in range(self.swing_window, len(candles) - self.swing_window):
            center = candles[i]
            left = candles[i - self.swing_window : i]
            right = candles[i + 1 : i + self.swing_window + 1]
            if kind == "high":
                if all(center.high > item.high for item in left + right):
                    points.append(SwingPoint(index=i, price=center.high, kind=kind))
            else:
                if all(center.low < item.low for item in left + right):
                    points.append(SwingPoint(index=i, price=center.low, kind=kind))
        return points

    def _determine_structure(self, highs: list[SwingPoint], lows: list[SwingPoint]) -> str:
        if len(highs) < 2 or len(lows) < 2:
            return "Range"

        recent_highs = highs[-2:]
        recent_lows = lows[-2:]
        higher_high = recent_highs[-1].price > recent_highs[-2].price
        higher_low = recent_lows[-1].price > recent_lows[-2].price
        lower_high = recent_highs[-1].price < recent_highs[-2].price
        lower_low = recent_lows[-1].price < recent_lows[-2].price

        if higher_high and higher_low:
            return "Bullish"
        if lower_high and lower_low:
            return "Bearish"
        return "Range"

    def _detect_bos_choch(
        self,
        candles: list[Candle],
        highs: list[SwingPoint],
        lows: list[SwingPoint],
        structure: str,
    ) -> tuple[list[str], list[str]]:
        bos: list[str] = []
        choch: list[str] = []
        last_close = candles[-1].close

        if highs:
            recent_high = highs[-1].price
            if last_close > recent_high:
                bos.append(f"Close broke above swing high {recent_high:.2f}")

        if lows:
            recent_low = lows[-1].price
            if last_close < recent_low:
                bos.append(f"Close broke below swing low {recent_low:.2f}")

        if structure == "Bullish" and lows and last_close < lows[-1].price:
            choch.append(f"Loss of bullish character below {lows[-1].price:.2f}")

        if structure == "Bearish" and highs and last_close > highs[-1].price:
            choch.append(f"Loss of bearish character above {highs[-1].price:.2f}")

        return bos, choch

    def _find_equal_levels(
        self,
        highs: list[SwingPoint],
        lows: list[SwingPoint],
        candles: list[Candle],
    ) -> tuple[list[str], list[str]]:
        tolerance = self._average_range(candles) * 0.25
        eqh: list[str] = []
        eql: list[str] = []

        for left, right in zip(highs[-6:-1], highs[-5:]):
            if abs(left.price - right.price) <= tolerance:
                eqh.append(f"EQH around {((left.price + right.price) / 2):.2f}")

        for left, right in zip(lows[-6:-1], lows[-5:]):
            if abs(left.price - right.price) <= tolerance:
                eql.append(f"EQL around {((left.price + right.price) / 2):.2f}")

        return eqh[-3:], eql[-3:]

    def _find_liquidity_sweeps(self, candles: list[Candle], eqh: list[str], eql: list[str]) -> list[str]:
        sweeps: list[str] = []
        if len(candles) < 4:
            return sweeps

        last = candles[-1]
        previous = candles[-2]
        average_range = self._average_range(candles)

        for item in eqh:
            level = float(item.split()[-1])
            if last.high > level and last.close < level and (last.high - level) <= average_range * 1.2:
                sweeps.append(f"Buyside liquidity sweep above {level:.2f}")

        for item in eql:
            level = float(item.split()[-1])
            if last.low < level and last.close > level and (level - last.low) <= average_range * 1.2:
                sweeps.append(f"Sellside liquidity sweep below {level:.2f}")

        if not sweeps:
            if last.high > previous.high and last.close < previous.high:
                sweeps.append(f"Short-term buyside sweep above {previous.high:.2f}")
            elif last.low < previous.low and last.close > previous.low:
                sweeps.append(f"Short-term sellside sweep below {previous.low:.2f}")

        return sweeps

    def _classify_liquidity(
        self,
        highs: list[SwingPoint],
        lows: list[SwingPoint],
        candles: list[Candle],
    ) -> tuple[list[str], list[str]]:
        current = candles[-1].close
        internal: list[str] = []
        external: list[str] = []

        for point in highs[-3:]:
            target = f"Resting highs at {point.price:.2f}"
            if point.price > current:
                external.append(target)
            else:
                internal.append(target)

        for point in lows[-3:]:
            target = f"Resting lows at {point.price:.2f}"
            if point.price < current:
                external.append(target)
            else:
                internal.append(target)

        return internal[:4], external[:4]

    def _find_fvgs(self, candles: list[Candle]) -> tuple[list[PriceZone], list[PriceZone]]:
        fvgs: list[PriceZone] = []
        inversion_fvgs: list[PriceZone] = []

        for i in range(2, len(candles)):
            left = candles[i - 2]
            middle = candles[i - 1]
            right = candles[i]

            if left.high < right.low:
                fvgs.append(PriceZone(low=left.high, high=right.low, label=f"Bullish FVG #{i}"))
            elif left.low > right.high:
                fvgs.append(PriceZone(low=right.high, high=left.low, label=f"Bearish FVG #{i}"))

            if middle.close < middle.open and left.high < right.low and right.close < right.open:
                inversion_fvgs.append(PriceZone(low=left.high, high=right.low, label=f"Inversion FVG #{i}"))
            if middle.close > middle.open and left.low > right.high and right.close > right.open:
                inversion_fvgs.append(PriceZone(low=right.high, high=left.low, label=f"Inversion FVG #{i}"))

        return fvgs[-4:], inversion_fvgs[-3:]

    def _find_order_blocks(self, candles: list[Candle]) -> list[PriceZone]:
        blocks: list[PriceZone] = []
        avg_range = self._average_range(candles)

        for i in range(1, len(candles) - 1):
            current = candles[i]
            nxt = candles[i + 1]
            body = abs(nxt.close - nxt.open)
            displacement = (nxt.high - nxt.low) >= avg_range * 1.3 and body >= avg_range * 0.7

            if current.close < current.open and nxt.close > nxt.open and displacement:
                blocks.append(PriceZone(low=current.low, high=current.open, label=f"Bullish OB #{i}"))
            elif current.close > current.open and nxt.close < nxt.open and displacement:
                blocks.append(PriceZone(low=current.open, high=current.high, label=f"Bearish OB #{i}"))

        return blocks[-5:]

    def _find_breaker_blocks(self, candles: list[Candle], order_blocks: list[PriceZone]) -> list[PriceZone]:
        current_price = candles[-1].close
        breakers: list[PriceZone] = []
        for block in order_blocks:
            if "Bullish" in block.label and current_price < block.low:
                breakers.append(PriceZone(low=block.low, high=block.high, label=block.label.replace("OB", "Breaker")))
            elif "Bearish" in block.label and current_price > block.high:
                breakers.append(PriceZone(low=block.low, high=block.high, label=block.label.replace("OB", "Breaker")))
        return breakers[-3:]

    def _find_mitigation_blocks(self, candles: list[Candle], order_blocks: list[PriceZone]) -> list[PriceZone]:
        touched: list[PriceZone] = []
        current = candles[-1]
        for block in order_blocks:
            if current.low <= block.high and current.high >= block.low:
                touched.append(PriceZone(low=block.low, high=block.high, label=block.label.replace("OB", "Mitigation")))
        return touched[-3:]

    def _find_dealing_range(self, candles: list[Candle]) -> tuple[PriceZone, PriceZone, float, float]:
        recent = candles[-50:]
        range_low = min(item.low for item in recent)
        range_high = max(item.high for item in recent)
        midpoint = (range_low + range_high) / 2
        premium_zone = PriceZone(low=midpoint, high=range_high, label="Premium")
        discount_zone = PriceZone(low=range_low, high=midpoint, label="Discount")
        return premium_zone, discount_zone, range_low, range_high

    def _build_narrative(
        self,
        structure: str,
        current_price: float,
        sweeps: list[str],
        order_blocks: list[PriceZone],
        fvgs: list[PriceZone],
        premium_zone: PriceZone,
        discount_zone: PriceZone,
        range_low: float,
        range_high: float,
        bos: list[str],
        choch: list[str],
    ) -> tuple[PriceZone | None, float | None, str, str, list[str]]:
        confluences: list[str] = []
        entry_zone: PriceZone | None = None
        invalidation: float | None = None

        in_discount = discount_zone.low <= current_price <= discount_zone.high
        in_premium = premium_zone.low <= current_price <= premium_zone.high

        if structure == "Bullish":
            confluences.append("Bullish market structure")
            if any("sellside" in item.lower() for item in sweeps):
                confluences.append("Sellside liquidity sweep")
            if in_discount:
                confluences.append("Discount pricing")
            bullish_ob = next((item for item in reversed(order_blocks) if "Bullish" in item.label), None)
            bullish_fvg = next((item for item in reversed(fvgs) if "Bullish" in item.label), None)

            if bullish_ob:
                confluences.append("Bullish order block")
                entry_zone = bullish_ob
                invalidation = bullish_ob.low
            elif bullish_fvg:
                confluences.append("Bullish fair value gap")
                entry_zone = bullish_fvg
                invalidation = bullish_fvg.low

            if bos:
                confluences.append("Bullish BOS")

            intention = "Accumulate below/inside discount then expand toward buyside liquidity."
            likely_path = f"Retrace into demand, then target {range_high:.2f} and higher if displacement holds."
            return entry_zone, invalidation, intention, likely_path, confluences

        if structure == "Bearish":
            confluences.append("Bearish market structure")
            if any("buyside" in item.lower() for item in sweeps):
                confluences.append("Buyside liquidity sweep")
            if in_premium:
                confluences.append("Premium pricing")
            bearish_ob = next((item for item in reversed(order_blocks) if "Bearish" in item.label), None)
            bearish_fvg = next((item for item in reversed(fvgs) if "Bearish" in item.label), None)

            if bearish_ob:
                confluences.append("Bearish order block")
                entry_zone = bearish_ob
                invalidation = bearish_ob.high
            elif bearish_fvg:
                confluences.append("Bearish fair value gap")
                entry_zone = bearish_fvg
                invalidation = bearish_fvg.high

            if bos:
                confluences.append("Bearish BOS")

            intention = "Distribute in premium and seek sellside liquidity below."
            likely_path = f"Retrace into supply, then target {range_low:.2f} and lower if displacement continues."
            return entry_zone, invalidation, intention, likely_path, confluences

        intention = "No clear institutional bias yet."
        likely_path = f"Price remains between {range_low:.2f} and {range_high:.2f} until a decisive displacement occurs."
        if choch:
            confluences.append("Potential character shift")
        return None, None, intention, likely_path, confluences

    def _average_range(self, candles: list[Candle]) -> float:
        recent = candles[-20:]
        return sum(item.high - item.low for item in recent) / len(recent)
