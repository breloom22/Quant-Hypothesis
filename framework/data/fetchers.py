"""데이터 수집 + 캐싱 (ccxt 기반)"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import ccxt
import pandas as pd
import yaml

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"


def _load_config() -> dict:
    config_path = Path(__file__).resolve().parents[2] / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _cache_key(symbol: str, timeframe: str, days: int, exchange: str) -> str:
    raw = f"{exchange}:{symbol}:{timeframe}:{days}"
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.parquet"


def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    days: int,
    exchange_id: str | None = None,
) -> pd.DataFrame:
    """OHLCV 데이터 fetch (캐시 우선)

    Args:
        symbol: 거래 페어 (예: "BTC/USDT:USDT")
        timeframe: 캔들 주기 (예: "1h", "4h", "1d")
        days: 가져올 기간 (일)
        exchange_id: 거래소 ID (기본: config의 default_exchange)

    Returns:
        DataFrame with columns: [timestamp, open, high, low, close, volume]
    """
    config = _load_config()
    if exchange_id is None:
        exchange_id = config["defaults"]["data"]["default_exchange"]

    cache_ttl = config["defaults"]["data"]["cache_ttl_hours"]
    key = _cache_key(symbol, timeframe, days, exchange_id)
    cached = _cache_path(key)

    # 캐시 확인
    if cached.exists():
        age_hours = (time.time() - cached.stat().st_mtime) / 3600
        if age_hours < cache_ttl:
            return pd.read_parquet(cached)

    # ccxt로 fetch
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True})

    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    all_candles: list[list] = []
    limit = 1000

    while True:
        candles = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=limit)
        if not candles:
            break
        all_candles.extend(candles)
        since_ms = candles[-1][0] + 1
        if len(candles) < limit:
            break
        time.sleep(exchange.rateLimit / 1000)

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    # 캐시 저장
    df.to_parquet(cached, index=False)

    return df


def fetch_funding_rate(
    symbol: str,
    days: int,
    exchange_id: str | None = None,
) -> pd.DataFrame:
    """펀딩비 이력 fetch (캐시 우선)

    Returns:
        DataFrame with columns: [timestamp, funding_rate]
    """
    config = _load_config()
    if exchange_id is None:
        exchange_id = config["defaults"]["data"]["default_exchange"]

    cache_ttl = config["defaults"]["data"]["cache_ttl_hours"]
    key = _cache_key(symbol, "funding", days, exchange_id)
    cached = _cache_path(key)

    if cached.exists():
        age_hours = (time.time() - cached.stat().st_mtime) / 3600
        if age_hours < cache_ttl:
            return pd.read_parquet(cached)

    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True})

    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    all_rates: list[dict] = []
    limit = 1000

    while True:
        rates = exchange.fetch_funding_rate_history(symbol, since=since_ms, limit=limit)
        if not rates:
            break
        all_rates.extend(rates)
        since_ms = rates[-1]["timestamp"] + 1
        if len(rates) < limit:
            break
        time.sleep(exchange.rateLimit / 1000)

    df = pd.DataFrame(all_rates)
    df = df[["timestamp", "fundingRate"]].rename(columns={"fundingRate": "funding_rate"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    df.to_parquet(cached, index=False)
    return df


def fetch_ohlcv_with_funding(
    symbol: str,
    timeframe: str,
    days: int,
    exchange_id: str | None = None,
) -> pd.DataFrame:
    """OHLCV + 펀딩비 병합 데이터

    펀딩비는 8h마다 정산. OHLCV 타임스탬프에 가장 가까운 펀딩비를 merge.
    """
    ohlcv = fetch_ohlcv(symbol, timeframe, days, exchange_id)
    fr = fetch_funding_rate(symbol, days, exchange_id)

    # 타임스탬프 기준 asof merge (가장 가까운 이전 펀딩비)
    ohlcv = ohlcv.sort_values("timestamp")
    fr = fr.sort_values("timestamp")

    merged = pd.merge_asof(
        ohlcv,
        fr,
        on="timestamp",
        direction="backward",
    )
    merged["funding_rate"] = merged["funding_rate"].ffill().fillna(0)
    return merged
