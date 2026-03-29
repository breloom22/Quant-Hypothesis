"""fr_flip 전략 — 펀딩비 부호 전환 기반 진입

generate_signals()가 반환하는 Series:
  1 = 롱 보유, -1 = 숏 보유, 0 = 플랫
backtest_engine.run()이 이 신호를 그대로 소비한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Callable


# ============================================================================
# funding_rate_sign_change — 진입 트리거
# ============================================================================

def compute_fr_sign_change_default(df: pd.DataFrame) -> pd.Series:
    """초기 구현: 단순 부호 전환. sign(fr_t) != sign(fr_t-1)
    +→- 전환 = 숏 과밀 → 1(롱), -→+ 전환 = 롱 과밀 → -1(숏)
    """
    fr = df["funding_rate"]
    fr_sign = np.sign(fr)
    prev_sign = fr_sign.shift(1)

    flip = (fr_sign != prev_sign) & prev_sign.notna() & (fr_sign != 0)

    # +→- : 숏 과밀 → 롱(1), -→+ : 롱 과밀 → 숏(-1)
    # 전환 후 현재가 음수면 숏 과밀 → 롱, 양수면 롱 과밀 → 숏
    # 즉 방향은 -fr_sign (과밀 방향의 반대)
    trigger = pd.Series(0, index=df.index)
    trigger[flip] = -fr_sign[flip].astype(int)
    return trigger


def compute_fr_sign_change_magnitude(df: pd.DataFrame, threshold: float = 0.0001) -> pd.Series:
    """개선: 부호 전환 + |FR| > threshold 조건"""
    fr = df["funding_rate"]
    fr_sign = np.sign(fr)
    prev_sign = fr_sign.shift(1)

    flip = (fr_sign != prev_sign) & prev_sign.notna() & (fr_sign != 0)
    magnitude_ok = (fr.abs() >= threshold) | (fr.shift(1).abs() >= threshold)

    trigger = pd.Series(0, index=df.index)
    trigger[flip & magnitude_ok] = -fr_sign[flip & magnitude_ok].astype(int)
    return trigger


def compute_fr_sign_change_consecutive(df: pd.DataFrame, n: int = 2) -> pd.Series:
    """개선: 전환 후 n봉 연속 동일 부호 유지 시 확정"""
    fr = df["funding_rate"]
    fr_sign = np.sign(fr)
    prev_sign = fr_sign.shift(1)

    flip = (fr_sign != prev_sign) & prev_sign.notna() & (fr_sign != 0)

    trigger = pd.Series(0, index=df.index)
    flip_indices = df.index[flip]

    for idx in flip_indices:
        loc = df.index.get_loc(idx)
        direction = -int(fr_sign.iloc[loc])
        # 전환 후 n봉 동일 부호 확인
        if loc + n < len(df):
            subsequent = fr_sign.iloc[loc:loc + n]
            if (subsequent == fr_sign.iloc[loc]).all():
                trigger.iloc[loc + n - 1] = direction

    return trigger


def compute_fr_sign_change_zscore(df: pd.DataFrame, window: int = 20, threshold: float = 1.0) -> pd.Series:
    """개선: Z-score 정규화 후 극단값 전환"""
    fr = df["funding_rate"]
    rolling_mean = fr.rolling(window, min_periods=1).mean()
    rolling_std = fr.rolling(window, min_periods=1).std().replace(0, np.nan).ffill()

    zscore = (fr - rolling_mean) / (rolling_std + 1e-10)
    z_sign = np.sign(zscore)
    prev_z_sign = z_sign.shift(1)

    flip = (z_sign != prev_z_sign) & prev_z_sign.notna() & (z_sign != 0)
    extreme = zscore.abs() >= threshold

    trigger = pd.Series(0, index=df.index)
    trigger[flip & extreme] = -z_sign[flip & extreme].astype(int)
    return trigger


# ============================================================================
# entry_timing — 진입 시점 조정
# ============================================================================

def apply_entry_default(trigger: pd.Series) -> pd.Series:
    """초기: 전환봉 종가 진입 (지연 없음)"""
    return trigger


def apply_entry_next_open(trigger: pd.Series) -> pd.Series:
    """개선: 다음봉 시가 진입 (1봉 지연)"""
    return trigger.shift(1).fillna(0).astype(int)


# ============================================================================
# generate_signals — 통합 함수
# ============================================================================

def generate_signals(
    df: pd.DataFrame,
    overrides: dict[str, Callable] | None = None,
    hold_bars: int = 3,
) -> pd.Series:
    """최종 포지션 신호 생성.

    Args:
        df: OHLCV + funding_rate 컬럼이 포함된 DataFrame
        overrides: 변수별 교체 함수 {"funding_rate_sign_change": fn, "entry_timing": fn}
        hold_bars: 포지션 보유 봉 수 (초기: 3봉 = 24h)

    Returns:
        pd.Series: 1=롱, -1=숏, 0=플랫 (연속 포지션 상태)
    """
    overrides = overrides or {}

    # 1. 진입 트리거
    fr_fn = overrides.get("funding_rate_sign_change", compute_fr_sign_change_default)
    trigger = fr_fn(df)

    # 2. 진입 타이밍
    entry_fn = overrides.get("entry_timing", apply_entry_default)
    entry = entry_fn(trigger)

    # 3. 트리거 → 연속 포지션 신호로 변환 (hold_bars 동안 유지)
    signal = pd.Series(0, index=df.index, dtype=int)
    position = 0
    bars_remaining = 0

    for i in range(len(df)):
        if bars_remaining > 0:
            signal.iloc[i] = position
            bars_remaining -= 1
            if bars_remaining == 0:
                position = 0

        # 새 진입 신호 (기존 포지션 없을 때만)
        if entry.iloc[i] != 0 and position == 0:
            position = int(entry.iloc[i])
            signal.iloc[i] = position
            bars_remaining = hold_bars - 1  # 현재 봉 포함

    return signal
