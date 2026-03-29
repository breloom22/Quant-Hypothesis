"""범용 백테스트 엔진"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


def _load_defaults() -> dict:
    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["defaults"]["backtest"]


@dataclass
class BacktestConfig:
    initial_capital: float = 10000.0
    fee_rate: float = 0.0004
    slippage: float = 0.0001

    @classmethod
    def from_defaults(cls) -> BacktestConfig:
        d = _load_defaults()
        return cls(**d)


@dataclass
class Trade:
    entry_time: Any
    exit_time: Any
    direction: int  # 1=long, -1=short
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    mfe: float  # Max Favorable Excursion (%)
    mae: float  # Max Adverse Excursion (%)
    bars_held: int


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.Series
    stats: dict[str, Any]


def run(
    df: pd.DataFrame,
    signals: pd.Series,
    config: BacktestConfig | None = None,
    tp: float | None = None,
    sl: float | None = None,
) -> BacktestResult:
    """백테스트 실행

    Args:
        df: OHLCV DataFrame (columns: timestamp, open, high, low, close, volume)
        signals: 신호 Series (1=long, -1=short, 0=flat). index는 df와 동일.
        config: 백테스트 설정
        tp: Take Profit (%) — None이면 신호 반전 시 청산
        sl: Stop Loss (%) — None이면 신호 반전 시 청산

    Returns:
        BacktestResult
    """
    if config is None:
        config = BacktestConfig.from_defaults()

    trades: list[Trade] = []
    equity = [config.initial_capital]
    position = 0  # 현재 포지션 방향
    entry_price = 0.0
    entry_time = None
    entry_idx = 0

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev_signal = signals.iloc[i - 1] if i > 0 else 0
        curr_signal = signals.iloc[i]

        close = row["close"]
        high = row["high"]
        low = row["low"]

        # TP/SL 체크 (포지션 보유 중)
        if position != 0:
            bars_held = i - entry_idx

            if position == 1:  # Long
                mfe_price = high
                mae_price = low
                mfe_pct = (mfe_price - entry_price) / entry_price * 100
                mae_pct = (entry_price - mae_price) / entry_price * 100
            else:  # Short
                mfe_price = low
                mae_price = high
                mfe_pct = (entry_price - mfe_price) / entry_price * 100
                mae_pct = (mae_price - entry_price) / entry_price * 100

            # SL hit
            if sl is not None and mae_pct >= sl:
                exit_price = entry_price * (1 - sl / 100) if position == 1 else entry_price * (1 + sl / 100)
                exit_price *= (1 - config.fee_rate - config.slippage)
                pnl_pct = -sl - (config.fee_rate + config.slippage) * 100 * 2
                pnl = equity[-1] * pnl_pct / 100

                trades.append(Trade(
                    entry_time=entry_time, exit_time=row["timestamp"],
                    direction=position, entry_price=entry_price, exit_price=exit_price,
                    pnl=pnl, pnl_pct=pnl_pct, mfe=mfe_pct, mae=sl,
                    bars_held=bars_held,
                ))
                equity.append(equity[-1] + pnl)
                position = 0
                continue

            # TP hit
            if tp is not None and mfe_pct >= tp:
                exit_price = entry_price * (1 + tp / 100) if position == 1 else entry_price * (1 - tp / 100)
                exit_price *= (1 - config.fee_rate - config.slippage)
                pnl_pct = tp - (config.fee_rate + config.slippage) * 100 * 2
                pnl = equity[-1] * pnl_pct / 100

                trades.append(Trade(
                    entry_time=entry_time, exit_time=row["timestamp"],
                    direction=position, entry_price=entry_price, exit_price=exit_price,
                    pnl=pnl, pnl_pct=pnl_pct, mfe=tp, mae=mae_pct,
                    bars_held=bars_held,
                ))
                equity.append(equity[-1] + pnl)
                position = 0
                continue

        # 신호 변화 처리
        if curr_signal != position:
            # 기존 포지션 청산
            if position != 0:
                exit_price = close * (1 - config.fee_rate - config.slippage)
                pnl_pct = position * (close - entry_price) / entry_price * 100
                pnl_pct -= (config.fee_rate + config.slippage) * 100 * 2
                pnl = equity[-1] * pnl_pct / 100
                bars_held = i - entry_idx

                # 이 캔들의 MFE/MAE 계산
                if position == 1:
                    mfe_pct = (high - entry_price) / entry_price * 100
                    mae_pct = (entry_price - low) / entry_price * 100
                else:
                    mfe_pct = (entry_price - low) / entry_price * 100
                    mae_pct = (high - entry_price) / entry_price * 100

                trades.append(Trade(
                    entry_time=entry_time, exit_time=row["timestamp"],
                    direction=position, entry_price=entry_price, exit_price=exit_price,
                    pnl=pnl, pnl_pct=pnl_pct, mfe=mfe_pct, mae=mae_pct,
                    bars_held=bars_held,
                ))
                equity.append(equity[-1] + pnl)

            # 새 포지션 진입
            if curr_signal != 0:
                position = int(curr_signal)
                entry_price = close * (1 + config.fee_rate + config.slippage)
                entry_time = row["timestamp"]
                entry_idx = i
            else:
                position = 0
        else:
            equity.append(equity[-1])

    # 미청산 포지션 강제 청산
    if position != 0:
        close = df.iloc[-1]["close"]
        pnl_pct = position * (close - entry_price) / entry_price * 100
        pnl_pct -= (config.fee_rate + config.slippage) * 100 * 2
        pnl = equity[-1] * pnl_pct / 100
        bars_held = len(df) - 1 - entry_idx

        trades.append(Trade(
            entry_time=entry_time, exit_time=df.iloc[-1]["timestamp"],
            direction=position, entry_price=entry_price, exit_price=close,
            pnl=pnl, pnl_pct=pnl_pct, mfe=0, mae=0,
            bars_held=bars_held,
        ))
        equity.append(equity[-1] + pnl)

    equity_series = pd.Series(equity)
    stats = calc_stats(trades, equity_series, config.initial_capital)

    return BacktestResult(trades=trades, equity_curve=equity_series, stats=stats)


def calc_stats(
    trades: list[Trade],
    equity_curve: pd.Series,
    initial_capital: float = 10000.0,
) -> dict[str, Any]:
    """백테스트 통계 계산"""
    if not trades:
        return {
            "N": 0, "WR": 0, "PF": 0, "Return": 0, "MDD": 0, "Sharpe": 0,
            "avg_pnl_pct": 0, "avg_win": 0, "avg_loss": 0,
            "max_win": 0, "max_loss": 0, "avg_bars_held": 0,
        }

    pnls = [t.pnl for t in trades]
    pnl_pcts = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    n = len(trades)
    wr = len(wins) / n * 100 if n > 0 else 0

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    total_return = (equity_curve.iloc[-1] - initial_capital) / initial_capital * 100

    # MDD
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max * 100
    mdd = abs(drawdown.min())

    # Sharpe (단순화: 일별 수익률 기준 아님, 트레이드 기준)
    pnl_arr = np.array(pnl_pcts)
    sharpe = (pnl_arr.mean() / pnl_arr.std() * np.sqrt(n)) if pnl_arr.std() > 0 else 0

    return {
        "N": n,
        "WR": round(wr, 1),
        "PF": round(pf, 2),
        "Return": round(total_return, 1),
        "MDD": round(mdd, 1),
        "Sharpe": round(sharpe, 2),
        "avg_pnl_pct": round(np.mean(pnl_pcts), 2),
        "avg_win": round(np.mean([t.pnl_pct for t in trades if t.pnl > 0]), 2) if wins else 0,
        "avg_loss": round(np.mean([t.pnl_pct for t in trades if t.pnl <= 0]), 2) if losses else 0,
        "max_win": round(max(pnl_pcts), 2),
        "max_loss": round(min(pnl_pcts), 2),
        "avg_bars_held": round(np.mean([t.bars_held for t in trades]), 1),
        "avg_mfe": round(np.mean([t.mfe for t in trades]), 2),
        "avg_mae": round(np.mean([t.mae for t in trades]), 2),
    }
