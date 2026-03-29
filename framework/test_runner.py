"""예측 테스트 실행 엔진"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .hypothesis_manager import load_hypothesis, save_hypothesis, strategy_dir
from .backtest_engine import run as run_backtest, BacktestConfig, calc_stats
from .data.fetchers import fetch_ohlcv


class TestRunner:
    """예측 테스트를 실행하고 결과를 hypothesis.yaml에 기록"""

    def run_all(self, strategy_name: str) -> dict[str, Any]:
        """모든 예측 테스트 실행"""
        h = load_hypothesis(strategy_name)
        results = {}

        for pred in h.phase_1.predictions:
            result = self._run_prediction_test(strategy_name, pred.id)
            results[pred.id] = result

            # 예측 상태 업데이트
            for p in h.phase_1.predictions:
                if p.id == pred.id:
                    p.status = "pass" if result.get("passed") else "fail"
                    p.result = result
                    break

        save_hypothesis(h)
        return results

    def run_single(self, strategy_name: str, pred_id: str) -> dict[str, Any]:
        """특정 예측 테스트 실행"""
        h = load_hypothesis(strategy_name)
        result = self._run_prediction_test(strategy_name, pred_id)

        for p in h.phase_1.predictions:
            if p.id == pred_id:
                p.status = "pass" if result.get("passed") else "fail"
                p.result = result
                break

        save_hypothesis(h)
        return result

    def run_isolation(self, strategy_name: str, variable: str) -> dict[str, Any]:
        """분리 테스트 실행 (한 변수만 교체)"""
        sdir = strategy_dir(strategy_name)
        tests_dir = sdir / "tests"

        results = {}
        for test_file in tests_dir.glob(f"test_isolation_{variable}*.py"):
            result = self._execute_test_file(test_file)
            results[test_file.stem] = result

        return results

    def run_crude_signal_test(
        self,
        strategy_name: str,
    ) -> dict[str, Any]:
        """초기 crude signal test — signals.py의 기본 설정으로 백테스트"""
        h = load_hypothesis(strategy_name)
        sdir = strategy_dir(strategy_name)

        # 데이터 fetch
        tm = h.phase_0.target_market
        df = fetch_ohlcv(
            symbol=tm.symbols[0] if tm.symbols else "BTC/USDT:USDT",
            timeframe=tm.timeframe or "1h",
            days=365,
            exchange_id=tm.exchange or None,
        )

        # signals.py 로드 및 실행
        signals_module = self._load_module(sdir / "signals.py", "signals")
        signals = signals_module.generate_signals(df)

        # 백테스트
        result = run_backtest(df, signals)

        return {
            "step": "crude_signal",
            "stats": result.stats,
            "n_trades": result.stats["N"],
            "passed": result.stats["PF"] > 1.0,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

    def _run_prediction_test(self, strategy_name: str, pred_id: str) -> dict[str, Any]:
        """예측 테스트 파일 실행"""
        sdir = strategy_dir(strategy_name)
        test_file = sdir / "tests" / f"test_{pred_id}.py"

        if not test_file.exists():
            return {"error": f"테스트 파일 없음: {test_file}", "passed": False}

        return self._execute_test_file(test_file)

    def _execute_test_file(self, test_file: Path) -> dict[str, Any]:
        """테스트 파일을 실행하고 결과를 반환"""
        try:
            module = self._load_module(test_file, test_file.stem)
            if hasattr(module, "run_test"):
                result = module.run_test()
                if isinstance(result, dict):
                    result["timestamp"] = datetime.now().isoformat(timespec="seconds")
                    return result
            return {"error": "run_test() 함수가 없거나 dict를 반환하지 않음", "passed": False}
        except Exception as e:
            return {"error": str(e), "passed": False}

    @staticmethod
    def _load_module(path: Path, name: str):
        """Python 모듈 동적 로드"""
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
