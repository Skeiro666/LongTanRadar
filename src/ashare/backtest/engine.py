from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import numpy as np
import pandas as pd

from ashare.brokers.paper import PaperBroker
from ashare.models import Bar, Order, OrderIntent, Side
from ashare.risk.guard import RiskGuard
from ashare.strategy.base import Strategy, StrategyContext


def row_to_bar(row: pd.Series) -> Bar:
    d = row["date"]
    if hasattr(d, "date"):
        d = d.date()
    elif isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return Bar(
        symbol=str(row["symbol"]),
        date=d,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
        amount=float(row.get("amount", 0.0) or 0.0),
        pct_chg=float(row.get("pct_chg", 0.0) or 0.0),
        is_st=bool(row.get("is_st", False)),
        is_halt=bool(row.get("is_halt", False)),
        limit_up=bool(row.get("limit_up", False)),
        limit_down=bool(row.get("limit_down", False)),
    )


def index_panel(panel: dict[str, pd.DataFrame]) -> dict[str, dict[date, Bar]]:
    indexed: dict[str, dict[date, Bar]] = {}
    for sym, df in panel.items():
        by_day: dict[date, Bar] = {}
        for _, row in df.iterrows():
            bar = row_to_bar(row)
            by_day[bar.date] = bar
        indexed[sym] = by_day
    return indexed


def trading_dates(panel: dict[str, pd.DataFrame], start: str, end: str) -> list[date]:
    start_d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    all_days: set[date] = set()
    for df in panel.values():
        for ts in pd.to_datetime(df["date"]):
            d = ts.date()
            if start_d <= d <= end_d:
                all_days.add(d)
    return sorted(all_days)


def history_asof(panel: dict[str, pd.DataFrame], as_of: date) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    cutoff = pd.Timestamp(as_of)
    for sym, df in panel.items():
        sub = df[pd.to_datetime(df["date"]) <= cutoff]
        if not sub.empty:
            out[sym] = sub
    return out


@dataclass
class BacktestResult:
    initial_balance: float
    final_equity: float
    total_return: float
    annualized: float
    max_drawdown: float
    sharpe: float
    turnover: float
    win_rate: float
    trades: int
    yearly: dict[str, float] = field(default_factory=dict)
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    trade_log: list[dict[str, Any]] = field(default_factory=list)
    # Extended metrics (Phase 14). Optional — filled when equity curve available.
    cagr: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    profit_factor: float = 0.0
    sample_split: str = "unspecified"  # in_sample | validation | out_of_sample | unspecified
    benchmark_return: float | None = None
    alpha: float | None = None
    beta: float | None = None
    information_ratio: float | None = None

    def summary(self) -> str:
        years = "\n".join(f"  {y}: {r:.2%}" for y, r in sorted(self.yearly.items()))
        return (
            f"Initial:     {self.initial_balance:,.2f}\n"
            f"Final:       {self.final_equity:,.2f}\n"
            f"Return:      {self.total_return:.2%}\n"
            f"Ann. Return: {self.annualized:.2%}\n"
            f"CAGR:        {self.cagr:.2%}\n"
            f"MaxDD:       {self.max_drawdown:.2%}\n"
            f"Sharpe:      {self.sharpe:.2f}\n"
            f"Sortino:     {self.sortino:.2f}\n"
            f"Calmar:      {self.calmar:.2f}\n"
            f"Turnover:    {self.turnover:.2f}\n"
            f"Win rate:    {self.win_rate:.2%}\n"
            f"ProfitFactor:{self.profit_factor:.2f}\n"
            f"Split:       {self.sample_split}\n"
            f"Trades:      {self.trades}\n"
            f"By year:\n{years or '  n/a'}"
        )


def extend_backtest_metrics(
    result: BacktestResult,
    *,
    benchmark_curve: list[tuple[str, float]] | None = None,
    sample_split: str = "unspecified",
) -> BacktestResult:
    """Fill Sortino/Calmar/PF and optional benchmark alpha/beta/IR. No fabricated bench."""
    result.cagr = result.annualized
    result.sample_split = sample_split
    if len(result.equity_curve) > 2:
        rets = pd.Series([e for _, e in result.equity_curve]).pct_change().dropna()
        downside = rets[rets < 0]
        if len(downside) > 1 and float(downside.std()) > 0:
            result.sortino = float(rets.mean() / downside.std() * np.sqrt(252))
        if result.max_drawdown > 1e-12:
            result.calmar = float(result.annualized / result.max_drawdown)
    sells = [float(t.get("realized_pnl", 0) or 0) for t in result.trade_log if t.get("side") == "SELL"]
    gains = sum(p for p in sells if p > 0)
    losses = -sum(p for p in sells if p < 0)
    result.profit_factor = float(gains / losses) if losses > 1e-12 else (float("inf") if gains > 0 else 0.0)
    if benchmark_curve and len(benchmark_curve) > 2 and len(result.equity_curve) > 2:
        be = pd.Series({d: e for d, e in benchmark_curve})
        se = pd.Series({d: e for d, e in result.equity_curve})
        aligned = pd.concat([se.rename("s"), be.rename("b")], axis=1).dropna()
        if len(aligned) > 5:
            sr = aligned["s"].pct_change().dropna()
            br = aligned["b"].pct_change().dropna()
            common = sr.index.intersection(br.index)
            sr, br = sr.loc[common], br.loc[common]
            result.benchmark_return = float(aligned["b"].iloc[-1] / aligned["b"].iloc[0] - 1.0)
            if float(br.std() or 0) > 0:
                cov = float(np.cov(sr, br)[0, 1])
                result.beta = cov / float(br.var())
                result.alpha = float((sr.mean() - result.beta * br.mean()) * 252)
                te = float((sr - br).std() or 0)
                result.information_ratio = float((sr - br).mean() / te * np.sqrt(252)) if te > 0 else 0.0
    return result


class BacktestEngine:
    """Daily event loop: T close signal -> T+1 fill. Shares T+1 / limit / fees with paper."""

    def __init__(
        self,
        strategy: Strategy,
        risk: RiskGuard,
        broker: PaperBroker,
        execute_at: str = "open",
        lot_size: int = 100,
    ) -> None:
        self.strategy = strategy
        self.risk = risk
        self.broker = broker
        self.execute_at = execute_at if execute_at in {"open", "close"} else "open"
        self.lot_size = lot_size

    def _marks(self, bars: dict[str, Bar], field: str = "close") -> dict[str, float]:
        return {s: float(getattr(b, field)) for s, b in bars.items()}

    def _bars_on(self, indexed: dict[str, dict[date, Bar]], d: date) -> dict[str, Bar]:
        return {s: days[d] for s, days in indexed.items() if d in days}

    def _execute_pending(self, bars: dict[str, Bar]) -> None:
        pending = list(self.broker.pending)
        self.broker.pending = []
        for raw in pending:
            intent = OrderIntent(
                symbol=raw["symbol"],
                side=Side(raw["side"]),
                quantity=int(raw["quantity"]),
                reason=raw.get("reason", ""),
                reduce_only=bool(raw.get("reduce_only", False)),
            )
            bar = bars.get(intent.symbol)
            if bar is None:
                self.broker.pending.append(raw)
                continue
            px = bar.open if self.execute_at == "open" else bar.close
            order = Order(
                symbol=intent.symbol,
                side=intent.side,
                quantity=intent.quantity,
                reason=intent.reason,
                reduce_only=intent.reduce_only,
            )
            is_reduce = intent.reduce_only or intent.side.value == "SELL"
            decision = self.risk.approve_order(order, is_reduce=is_reduce)
            if not decision.allowed:
                continue
            self.broker.execute(order, bar, px)

    def _queue(self, intents: list[OrderIntent]) -> None:
        for it in self.risk.filter_intents(intents):
            self.broker.pending.append(
                {
                    "symbol": it.symbol,
                    "side": it.side.value,
                    "quantity": it.quantity,
                    "reason": it.reason,
                    "reduce_only": it.reduce_only,
                }
            )

    def run(
        self,
        panel: dict[str, pd.DataFrame],
        start: str,
        end: str,
        skip_until: Optional[str] = None,
    ) -> BacktestResult:
        indexed = index_panel(panel)
        dates = trading_dates(panel, start, end)
        if skip_until:
            cut = date.fromisoformat(skip_until)
            dates = [d for d in dates if d > cut]

        initial = self.broker.cash + self.broker.market_value({})
        if initial <= 0:
            initial = self.broker.initial_balance
        equity_curve: list[tuple[str, float]] = []
        peak = initial
        max_dd = 0.0
        notional_traded = 0.0
        self.strategy.reset()
        inited = False

        for i, d in enumerate(dates):
            bars = self._bars_on(indexed, d)
            if not bars:
                continue
            open_marks = self._marks(bars, "open")
            close_marks = self._marks(bars, "close")
            self.broker.session_open(d, equity_mark=open_marks or close_marks)
            self._execute_pending(bars)

            equity = self.broker.get_equity(close_marks)
            self.risk.update_equity(equity, self.broker.daily_start_equity)

            hist = history_asof(panel, d)
            nxt = dates[i + 1] if i + 1 < len(dates) else None
            ctx = StrategyContext(
                as_of=d,
                equity=equity,
                cash=self.broker.cash,
                positions=dict(self.broker.positions),
                bars_today=bars,
                history=hist,
                lot_size=self.lot_size,
                is_month_end=nxt is None or nxt.month != d.month,
            )
            if not inited:
                self.strategy.on_init(ctx)
                inited = True
            intents = self.strategy.on_date(ctx)
            self._queue(intents)

            equity = self.broker.get_equity(close_marks)
            equity_curve.append((d.isoformat(), equity))
            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
            self.broker._persist(close_marks)

        trades = [t for t in self.broker.ledger.trades]
        notional_traded = sum(float(t.get("price", 0)) * int(t.get("quantity", 0) or 0) for t in trades)
        final = equity_curve[-1][1] if equity_curve else initial
        n = max(len(equity_curve), 1)
        years = n / 252.0
        total_return = final / initial - 1.0 if initial else 0.0
        annualized = (1.0 + total_return) ** (1.0 / years) - 1.0 if years > 0 and final > 0 else 0.0
        rets = pd.Series([e for _, e in equity_curve]).pct_change().dropna()
        sharpe = 0.0
        if len(rets) > 1 and float(rets.std()) > 0:
            sharpe = float(rets.mean() / rets.std() * np.sqrt(252))
        avg_equity = float(np.mean([e for _, e in equity_curve])) if equity_curve else initial
        turnover = (notional_traded / avg_equity / max(years, 1e-9)) if avg_equity else 0.0
        pnls = [float(t.get("realized_pnl", 0) or 0) for t in trades if t.get("side") == "SELL"]
        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / len(pnls) if pnls else 0.0

        yearly: dict[str, float] = {}
        by_year: dict[str, list[float]] = {}
        for ds, eq in equity_curve:
            by_year.setdefault(ds[:4], []).append(eq)
        for y, xs in by_year.items():
            if xs[0]:
                yearly[y] = xs[-1] / xs[0] - 1.0

        result = BacktestResult(
            initial_balance=initial,
            final_equity=final,
            total_return=total_return,
            annualized=annualized,
            max_drawdown=max_dd,
            sharpe=sharpe,
            turnover=turnover,
            win_rate=win_rate,
            trades=len(trades),
            yearly=yearly,
            equity_curve=equity_curve,
            trade_log=list(trades),
        )
        return extend_backtest_metrics(result)


def broker_from_cfg(cfg: dict[str, Any], *, persist: bool, reset: bool, state_file: str | None = None) -> PaperBroker:
    paper = cfg.get("paper", {})
    costs = cfg.get("costs", {})
    trading = cfg.get("trading", {})
    return PaperBroker(
        initial_balance=float(paper.get("initial_balance", 1_000_000)),
        commission_rate=float(costs.get("commission_rate", 0.00025)),
        min_commission=float(costs.get("min_commission", 5.0)),
        stamp_tax_rate=float(costs.get("stamp_tax_rate", 0.0005)),
        transfer_fee_rate=float(costs.get("transfer_fee_rate", 0.00001)),
        slippage_bps=float(costs.get("slippage_bps", 5.0)),
        lot_size=int(trading.get("lot_size", 100)),
        state_file=state_file or paper.get("state_file", "data/paper_state.json"),
        reset_on_start=reset,
        persist=persist,
    )
