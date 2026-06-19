from __future__ import annotations

import csv
import logging
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app.config import Settings
from app.models import AnalysisResult, Candle, TradePlan
from app.services.analysis import SMCAnalyzer
from app.services.market_data import MarketDataProvider
from app.services.signals import SignalBuilder
from app.services.telegram_notifier import TelegramNotifier

LOGGER = logging.getLogger(__name__)
REPORTS_DIR = Path("reports")
BACKTEST_STATE_FILE = Path("backtest_state.json")


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    direction: str
    entry_price: float
    stop_loss: float
    take_profit_1: float
    exit_price: float
    outcome_r: float
    result: str


@dataclass(frozen=True, slots=True)
class BacktestReport:
    generated_at: datetime
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    net_r: float
    max_drawdown_r: float
    profit_factor: float
    equity_curve: list[float]
    trades: list[BacktestTrade]
    image_path: Path
    csv_path: Path


class BacktestService:
    def __init__(
        self,
        settings: Settings,
        provider: MarketDataProvider,
        analyzer: SMCAnalyzer,
        signal_builder: SignalBuilder,
        notifier: TelegramNotifier,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.analyzer = analyzer
        self.signal_builder = signal_builder
        self.notifier = notifier

    async def maybe_run_and_send(self, force: bool = False) -> None:
        if not self.settings.enable_backtest_reports:
            return
        if not force and not self._is_due():
            return

        report = await self._run_backtest()
        if report.total_trades == 0:
            await self.notifier.send_message(
                "Backtest Report\n\nهیچ معامله‌ای در دیتای بک‌تست تولید نشد. "
                "فیلترها خیلی سخت‌گیرانه‌اند یا ستاپی در این بازه وجود نداشته است."
            )
            self._save_last_run(report.generated_at)
            return

        caption = (
            f"Backtest | {self.settings.symbol}\n"
            f"Trades: {report.total_trades}\n"
            f"Wins: {report.wins} | Losses: {report.losses}\n"
            f"Win Rate: {report.win_rate:.2f}%\n"
            f"Net R: {report.net_r:.2f}\n"
            f"Max DD: {report.max_drawdown_r:.2f}R\n"
            f"Profit Factor: {report.profit_factor:.2f}"
        )
        await self.notifier.send_photo(report.image_path, caption=caption)
        await self.notifier.send_message(
            f"Backtest files generated:\n- Image: {report.image_path}\n- CSV: {report.csv_path}"
        )
        self._save_last_run(report.generated_at)

    async def _run_backtest(self) -> BacktestReport:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        datasets: dict[str, list[Candle]] = {}
        timestamps_by_timeframe: dict[str, list[datetime]] = {}
        for timeframe in self.settings.top_down_timeframes:
            candles = await self.provider.fetch_ohlc(
                symbol=self.settings.symbol,
                timeframe=timeframe,
                limit=self.settings.backtest_lookback_bars,
            )
            datasets[timeframe] = candles
            timestamps_by_timeframe[timeframe] = [item.timestamp for item in candles]

        execution_candles = datasets[self.settings.execution_timeframe]
        trades: list[BacktestTrade] = []
        last_signal_time: datetime | None = None

        for i in range(self.settings.backtest_warmup_bars, len(execution_candles) - 2):
            signal_candle = execution_candles[i]
            if last_signal_time is not None:
                min_gap = timedelta(minutes=self.settings.min_signal_interval_minutes)
                if signal_candle.timestamp - last_signal_time < min_gap:
                    continue

            analyses = self._build_analyses_at_time(
                signal_time=signal_candle.timestamp,
                datasets=datasets,
                timestamps_by_timeframe=timestamps_by_timeframe,
            )
            if len(analyses) != len(self.settings.top_down_timeframes):
                continue

            current_session = self.analyzer.session_label(signal_candle.timestamp)
            plan = self.signal_builder.build_plan(
                symbol=self.settings.symbol,
                analyses=analyses,
                current_session=current_session,
            )
            if not plan.is_trade:
                continue

            trade = self._simulate_trade(
                plan=plan,
                execution_candles=execution_candles,
                signal_index=i,
            )
            if trade is not None:
                trades.append(trade)
                last_signal_time = trade.signal_time

        image_path = REPORTS_DIR / "backtest_equity_curve.png"
        csv_path = REPORTS_DIR / "backtest_trades.csv"

        equity_curve = self._build_equity_curve(trades)
        self._write_csv(csv_path, trades)
        self._write_chart(image_path, equity_curve)

        total_trades = len(trades)
        wins = sum(1 for trade in trades if trade.outcome_r > 0)
        losses = sum(1 for trade in trades if trade.outcome_r <= 0)
        gross_profit = sum(trade.outcome_r for trade in trades if trade.outcome_r > 0)
        gross_loss = abs(sum(trade.outcome_r for trade in trades if trade.outcome_r < 0))
        win_rate = (wins / total_trades * 100) if total_trades else 0.0
        net_r = sum(trade.outcome_r for trade in trades)
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else gross_profit
        max_drawdown_r = self._calculate_max_drawdown(equity_curve)

        return BacktestReport(
            generated_at=datetime.now(UTC),
            total_trades=total_trades,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            net_r=net_r,
            max_drawdown_r=max_drawdown_r,
            profit_factor=profit_factor,
            equity_curve=equity_curve,
            trades=trades,
            image_path=image_path,
            csv_path=csv_path,
        )

    def _build_analyses_at_time(
        self,
        signal_time: datetime,
        datasets: dict[str, list[Candle]],
        timestamps_by_timeframe: dict[str, list[datetime]],
    ) -> list[AnalysisResult]:
        analyses: list[AnalysisResult] = []
        for timeframe in self.settings.top_down_timeframes:
            candles = datasets[timeframe]
            timestamps = timestamps_by_timeframe[timeframe]
            end_index = bisect_right(timestamps, signal_time)
            sliced = candles[:end_index]
            if len(sliced) < 40:
                return []
            analyses.append(self.analyzer.analyze(timeframe=timeframe, candles=sliced))
        return analyses

    def _simulate_trade(
        self,
        plan: TradePlan,
        execution_candles: list[Candle],
        signal_index: int,
    ) -> BacktestTrade | None:
        if not plan.is_trade:
            return None
        if plan.entry_low is None or plan.entry_high is None or plan.stop_loss is None or plan.take_profit_1 is None:
            return None

        entry_price = (plan.entry_low + plan.entry_high) / 2
        risk_distance = abs(entry_price - plan.stop_loss)
        if risk_distance <= 0:
            return None

        entry_index: int | None = None
        entry_time: datetime | None = None
        last_entry_scan = min(
            len(execution_candles),
            signal_index + 1 + self.settings.backtest_entry_wait_bars,
        )

        for i in range(signal_index + 1, last_entry_scan):
            candle = execution_candles[i]
            if candle.low <= plan.entry_high and candle.high >= plan.entry_low:
                entry_index = i
                entry_time = candle.timestamp
                break

        if entry_index is None or entry_time is None:
            return None

        final_index = min(
            len(execution_candles),
            entry_index + 1 + self.settings.backtest_max_holding_bars,
        )

        for i in range(entry_index, final_index):
            candle = execution_candles[i]
            if plan.direction == "BUY":
                if candle.low <= plan.stop_loss:
                    return BacktestTrade(
                        signal_time=execution_candles[signal_index].timestamp,
                        entry_time=entry_time,
                        exit_time=candle.timestamp,
                        direction=plan.direction,
                        entry_price=entry_price,
                        stop_loss=plan.stop_loss,
                        take_profit_1=plan.take_profit_1,
                        exit_price=plan.stop_loss,
                        outcome_r=-1.0,
                        result="LOSS",
                    )
                if candle.high >= plan.take_profit_1:
                    outcome_r = abs(plan.take_profit_1 - entry_price) / risk_distance
                    return BacktestTrade(
                        signal_time=execution_candles[signal_index].timestamp,
                        entry_time=entry_time,
                        exit_time=candle.timestamp,
                        direction=plan.direction,
                        entry_price=entry_price,
                        stop_loss=plan.stop_loss,
                        take_profit_1=plan.take_profit_1,
                        exit_price=plan.take_profit_1,
                        outcome_r=outcome_r,
                        result="WIN",
                    )

            if plan.direction == "SELL":
                if candle.high >= plan.stop_loss:
                    return BacktestTrade(
                        signal_time=execution_candles[signal_index].timestamp,
                        entry_time=entry_time,
                        exit_time=candle.timestamp,
                        direction=plan.direction,
                        entry_price=entry_price,
                        stop_loss=plan.stop_loss,
                        take_profit_1=plan.take_profit_1,
                        exit_price=plan.stop_loss,
                        outcome_r=-1.0,
                        result="LOSS",
                    )
                if candle.low <= plan.take_profit_1:
                    outcome_r = abs(entry_price - plan.take_profit_1) / risk_distance
                    return BacktestTrade(
                        signal_time=execution_candles[signal_index].timestamp,
                        entry_time=entry_time,
                        exit_time=candle.timestamp,
                        direction=plan.direction,
                        entry_price=entry_price,
                        stop_loss=plan.stop_loss,
                        take_profit_1=plan.take_profit_1,
                        exit_price=plan.take_profit_1,
                        outcome_r=outcome_r,
                        result="WIN",
                    )

        final_candle = execution_candles[final_index - 1]
        if plan.direction == "BUY":
            floating_r = (final_candle.close - entry_price) / risk_distance
        else:
            floating_r = (entry_price - final_candle.close) / risk_distance

        return BacktestTrade(
            signal_time=execution_candles[signal_index].timestamp,
            entry_time=entry_time,
            exit_time=final_candle.timestamp,
            direction=plan.direction,
            entry_price=entry_price,
            stop_loss=plan.stop_loss,
            take_profit_1=plan.take_profit_1,
            exit_price=final_candle.close,
            outcome_r=floating_r,
            result="WIN" if floating_r > 0 else "LOSS",
        )

    def _build_equity_curve(self, trades: list[BacktestTrade]) -> list[float]:
        curve: list[float] = [0.0]
        running = 0.0
        for trade in trades:
            running += trade.outcome_r
            curve.append(running)
        return curve

    def _calculate_max_drawdown(self, equity_curve: list[float]) -> float:
        peak = equity_curve[0] if equity_curve else 0.0
        max_drawdown = 0.0
        for point in equity_curve:
            peak = max(peak, point)
            drawdown = peak - point
            max_drawdown = max(max_drawdown, drawdown)
        return max_drawdown

    def _write_csv(self, csv_path: Path, trades: list[BacktestTrade]) -> None:
        with csv_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "signal_time",
                    "entry_time",
                    "exit_time",
                    "direction",
                    "entry_price",
                    "stop_loss",
                    "take_profit_1",
                    "exit_price",
                    "outcome_r",
                    "result",
                ]
            )
            for trade in trades:
                writer.writerow(
                    [
                        trade.signal_time.isoformat(),
                        trade.entry_time.isoformat(),
                        trade.exit_time.isoformat(),
                        trade.direction,
                        f"{trade.entry_price:.2f}",
                        f"{trade.stop_loss:.2f}",
                        f"{trade.take_profit_1:.2f}",
                        f"{trade.exit_price:.2f}",
                        f"{trade.outcome_r:.4f}",
                        trade.result,
                    ]
                )

    def _write_chart(self, image_path: Path, equity_curve: list[float]) -> None:
        plt.figure(figsize=(10, 6))
        plt.plot(equity_curve)
        plt.title(f"Backtest Equity Curve | {self.settings.symbol}")
        plt.xlabel("Closed Trades")
        plt.ylabel("Cumulative R")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(image_path, dpi=150)
        plt.close()

    def _is_due(self) -> bool:
        if not BACKTEST_STATE_FILE.exists():
            return True

        try:
            payload = BACKTEST_STATE_FILE.read_text(encoding="utf-8").strip()
            if not payload:
                return True
            last_run = datetime.fromisoformat(payload)
        except Exception:
            return True

        return datetime.now(UTC) - last_run >= timedelta(hours=self.settings.backtest_interval_hours)

    def _save_last_run(self, when: datetime) -> None:
        BACKTEST_STATE_FILE.write_text(when.isoformat(), encoding="utf-8")
