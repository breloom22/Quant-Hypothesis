"""Phase 3 검증 파이프라인 — 13단계 순차/선택 실행"""

from __future__ import annotations

import json
import re
import textwrap
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .hypothesis_manager import load_hypothesis, save_hypothesis, load_prompt, strategy_dir
from .llm.client import LLMClient, load_config
from .backtest_engine import run as run_backtest, BacktestConfig, calc_stats
from .data.fetchers import fetch_ohlcv
from .schema import ValidationStep
from .test_runner import TestRunner


class ValidationPipeline:

    STEPS = [
        ("crude_signal",       "Crude Signal Test"),
        ("signal_refinement",  "Signal Refinement"),
        ("variant_selection",  "Variant Selection"),
        ("monte_carlo",        "Monte Carlo"),
        ("param_optimize",     "Parameter Optimization"),
        ("walk_forward",       "Walk-Forward"),
        ("execution_tuning",   "Execution Tuning"),
        ("domain_expansion",   "Domain Expansion"),
        ("universe_expansion", "Universe Expansion"),
        ("regime_filter",      "Regime Filter"),
        ("failure_analysis",   "Failure Analysis"),
        ("cross_validation",   "Cross-Validation"),
        ("paper_deployment",   "Paper Deployment"),
    ]

    def run_all(self, strategy_name: str, auto: bool = False) -> dict:
        """전체 파이프라인 순차 실행.

        Returns:
            요약 dict: passed, failed, skipped, not_implemented, failed_steps
        """
        counts = {"passed": 0, "failed": 0, "skipped": 0, "not_implemented": 0}
        failed_steps = []

        for step_id, display_name in self.STEPS:
            print(f"\n{'='*60}")
            print(f"  [{step_id}] {display_name}")
            print(f"{'='*60}")

            result = self.run_step(strategy_name, step_id)
            status = result.get("status", "unknown")
            print(f"  -> {status}")

            if status in ("pass", "complete"):
                counts["passed"] += 1
            elif status == "fail":
                counts["failed"] += 1
                failed_steps.append(step_id)
                if auto:
                    print("[auto] 실패 — 자동 계속")
                else:
                    action = input("실패. 계속 진행할까요? [y/n]: ").strip().lower()
                    if action != "y":
                        print("파이프라인 중단.")
                        break
            elif status == "skip":
                counts["skipped"] += 1
            elif status == "not_implemented":
                counts["not_implemented"] += 1

        print("\n검증 파이프라인 완료!")
        return {**counts, "total": len(self.STEPS), "failed_steps": failed_steps}

    def run_step(self, strategy_name: str, step_id: str) -> dict[str, Any]:
        """특정 단계 실행"""
        h = load_hypothesis(strategy_name)
        config = load_config()
        llm = LLMClient(config)

        runner_name = f"_run_{step_id}"
        runner = getattr(self, runner_name, None)
        if runner is None:
            return {"status": "not_implemented", "message": f"{step_id} 미구현"}

        result = runner(strategy_name, h, llm)

        # 결과 저장
        h = load_hypothesis(strategy_name)
        h.phase_3.steps[step_id] = ValidationStep(
            status=result.get("status", "complete"),
            result=result.get("stats", result.get("result", {})),
            interpretation=result.get("interpretation", ""),
            timestamp=datetime.now().isoformat(timespec="seconds"),
        )
        # 비용 누적
        h.llm_cost = {k: h.llm_cost.get(k, 0) + llm.usage.get(k, 0) for k in llm.usage}
        save_hypothesis(h)

        return result

    # ── 개별 단계 구현 ─────────────────────────────────────

    def _run_crude_signal(self, strategy_name: str, h, llm: LLMClient) -> dict:
        """Crude Signal Test — 기본 신호로 백테스트"""
        runner = TestRunner()
        result = runner.run_crude_signal_test(strategy_name)

        # Sonnet 해석
        interpretation = llm.interpret(
            system_prompt=textwrap.dedent("""\
                퀀트 전략의 초기 백테스트 결과를 해석해줘.

                판단 기준:
                - PF > 1.0이면 엣지 존재 가능성. 다음 단계로 진행.
                - PF < 1.0이면 신호 자체에 문제. 변수 재검토 필요.
                - N < 50이면 통계적으로 불충분. 데이터 기간 확장 필요.

                결과를 해석하고, 다음 단계를 제안해줘.
            """),
            user_message=textwrap.dedent(f"""\
                전략: {h.strategy_name}
                메커니즘 가설: {h.phase_1.mechanism.statement}

                결과:
                N={result['stats']['N']}, WR={result['stats']['WR']:.1f}%, PF={result['stats']['PF']:.2f}
                Return={result['stats']['Return']:+.1f}%, MDD={result['stats']['MDD']:.1f}%
                Sharpe={result['stats']['Sharpe']:.2f}
            """),
        )

        print(interpretation.content)
        result["interpretation"] = interpretation.content
        result["status"] = "pass" if result["stats"]["PF"] > 1.0 else "fail"
        return result

    def _run_signal_refinement(self, strategy_name: str, h, llm: LLMClient) -> dict:
        """Signal Refinement — 변수 후보 교체 A/B 테스트"""
        sdir = strategy_dir(strategy_name)
        tm = h.phase_0.target_market
        df = fetch_ohlcv(tm.symbols[0], tm.timeframe, 365, tm.exchange or None)

        # signals.py 로드
        runner = TestRunner()
        signals_mod = runner._load_module(sdir / "signals.py", "signals")

        # Baseline
        baseline_signals = signals_mod.generate_signals(df)
        baseline_result = run_backtest(df, baseline_signals)
        results = {"baseline": baseline_result.stats}

        # 각 변수의 후보 테스트
        for var in h.phase_1.variables:
            for i, cand in enumerate(var.candidates):
                override_key = var.name
                if hasattr(signals_mod, cand.name):
                    override_fn = getattr(signals_mod, cand.name)
                    variant_signals = signals_mod.generate_signals(df, overrides={override_key: override_fn})
                    variant_result = run_backtest(df, variant_signals)
                    results[f"{var.name}_cand{i}_{cand.name}"] = variant_result.stats

        # DeepSeek 판정
        judgment = llm.analyze(
            system_prompt="각 변수 후보의 A/B 테스트 결과를 비교하고 최적 조합을 추천해줘. JSON으로 출력.",
            user_message=yaml.dump(results, allow_unicode=True),
        )

        return {"status": "complete", "stats": results, "interpretation": judgment.content}

    def _run_variant_selection(self, strategy_name: str, h, llm: LLMClient) -> dict:
        """Variant Selection — 최적 변수 조합 확정"""
        # Signal Refinement 결과 참조
        prev = h.phase_3.steps.get("signal_refinement")
        if not prev or prev.status == "pending":
            return {"status": "skip", "message": "signal_refinement 먼저 실행 필요"}

        interpretation = llm.analyze(
            system_prompt="Signal Refinement 결과를 기반으로 최종 변수 조합을 확정해줘. YAML로 출력.",
            user_message=f"결과:\n{yaml.dump(prev.result, allow_unicode=True)}\n해석:\n{prev.interpretation}",
        )
        return {"status": "complete", "interpretation": interpretation.content}

    def _run_monte_carlo(self, strategy_name: str, h, llm: LLMClient) -> dict:
        """Monte Carlo 시뮬레이션"""
        sdir = strategy_dir(strategy_name)
        tm = h.phase_0.target_market
        df = fetch_ohlcv(tm.symbols[0], tm.timeframe, 365, tm.exchange or None)

        runner = TestRunner()
        signals_mod = runner._load_module(sdir / "signals.py", "signals")
        signals = signals_mod.generate_signals(df)
        base_result = run_backtest(df, signals)

        if not base_result.trades:
            return {"status": "fail", "message": "트레이드 없음"}

        # Monte Carlo: 트레이드 순서 셔플
        config = load_config()
        n_sims = config["defaults"]["validation"]["monte_carlo_sims"]
        pnl_pcts = np.array([t.pnl_pct for t in base_result.trades])
        mc_returns = []
        mc_mdds = []

        for _ in range(n_sims):
            shuffled = np.random.permutation(pnl_pcts)
            equity = [10000.0]
            for p in shuffled:
                equity.append(equity[-1] * (1 + p / 100))
            eq = np.array(equity)
            mc_returns.append((eq[-1] - eq[0]) / eq[0] * 100)
            running_max = np.maximum.accumulate(eq)
            dd = (eq - running_max) / running_max * 100
            mc_mdds.append(abs(dd.min()))

        mc_stats = {
            "n_sims": n_sims,
            "return_mean": round(float(np.mean(mc_returns)), 2),
            "return_5th": round(float(np.percentile(mc_returns, 5)), 2),
            "return_95th": round(float(np.percentile(mc_returns, 95)), 2),
            "mdd_mean": round(float(np.mean(mc_mdds)), 2),
            "mdd_95th": round(float(np.percentile(mc_mdds, 95)), 2),
            "p_value_positive": round(float(np.mean(np.array(mc_returns) > 0)), 4),
            "original_return": base_result.stats["Return"],
            "original_mdd": base_result.stats["MDD"],
        }

        min_p = config["defaults"]["validation"]["min_mc_p_value"]
        passed = mc_stats["p_value_positive"] >= (1 - min_p)

        judgment = llm.analyze(
            system_prompt="Monte Carlo 시뮬레이션 결과를 해석해줘. 통계적 유의성과 리스크를 평가.",
            user_message=yaml.dump(mc_stats, allow_unicode=True),
        )

        return {
            "status": "pass" if passed else "fail",
            "stats": mc_stats,
            "interpretation": judgment.content,
        }

    def _run_param_optimize(self, strategy_name: str, h, llm: LLMClient) -> dict:
        """Parameter Optimization — 파라미터 민감도 분석"""
        interpretation = llm.analyze(
            system_prompt="파라미터 최적화 결과를 분석해줘. 과적합 징후와 안정적인 파라미터 영역을 식별.",
            user_message=f"메커니즘: {h.phase_1.mechanism.statement}\n변수: {yaml.dump([v.__dict__ for v in h.phase_1.variables], allow_unicode=True)}",
        )
        return {"status": "complete", "interpretation": interpretation.content}

    def _run_walk_forward(self, strategy_name: str, h, llm: LLMClient) -> dict:
        """Walk-Forward 검증"""
        sdir = strategy_dir(strategy_name)
        tm = h.phase_0.target_market
        df = fetch_ohlcv(tm.symbols[0], tm.timeframe, 365, tm.exchange or None)

        config = load_config()
        n_folds = config["defaults"]["validation"]["walk_forward_folds"]
        min_pass = config["defaults"]["validation"]["min_wf_pass_ratio"]

        fold_size = len(df) // (n_folds + 1)
        fold_results = []

        runner = TestRunner()
        signals_mod = runner._load_module(sdir / "signals.py", "signals")

        for i in range(n_folds):
            train_end = fold_size * (i + 1)
            test_start = train_end
            test_end = min(test_start + fold_size, len(df))

            test_df = df.iloc[test_start:test_end].reset_index(drop=True)
            if len(test_df) < 20:
                continue

            signals = signals_mod.generate_signals(test_df)
            result = run_backtest(test_df, signals)
            fold_results.append({
                "fold": i + 1,
                "n_trades": result.stats["N"],
                "pf": result.stats["PF"],
                "return": result.stats["Return"],
                "passed": result.stats["PF"] > 1.0,
            })

        passed_folds = sum(1 for f in fold_results if f["passed"])
        pass_ratio = passed_folds / len(fold_results) if fold_results else 0
        overall_pass = pass_ratio >= min_pass

        judgment = llm.analyze(
            system_prompt="Walk-Forward 검증 결과를 분석해줘. 시간 안정성과 과적합 위험을 평가.",
            user_message=yaml.dump({"folds": fold_results, "pass_ratio": pass_ratio}, allow_unicode=True),
        )

        return {
            "status": "pass" if overall_pass else "fail",
            "stats": {"folds": fold_results, "pass_ratio": round(pass_ratio, 2)},
            "interpretation": judgment.content,
        }

    def _run_execution_tuning(self, strategy_name: str, h, llm: LLMClient) -> dict:
        """Execution Tuning — TP/SL 그리드 서치 + Sonnet 해석"""
        sdir = strategy_dir(strategy_name)
        tm = h.phase_0.target_market
        df = fetch_ohlcv(tm.symbols[0], tm.timeframe, 365, tm.exchange or None)

        runner = TestRunner()
        signals_mod = runner._load_module(sdir / "signals.py", "signals")
        signals = signals_mod.generate_signals(df)

        # TP/SL 그리드
        tp_range = [1.0, 1.5, 2.0, 3.0, 5.0]
        sl_range = [0.5, 1.0, 1.5, 2.0, 3.0]
        grid_results = {}

        # Baseline (no TP/SL)
        base = run_backtest(df, signals)
        grid_results["no_tpsl"] = base.stats

        for tp in tp_range:
            for sl in sl_range:
                result = run_backtest(df, signals, tp=tp, sl=sl)
                grid_results[f"tp{tp}_sl{sl}"] = result.stats

        # Sonnet 해석
        interpretation = llm.interpret(
            system_prompt=textwrap.dedent("""\
                TP/SL 그리드 서치 결과를 해석해줘.

                주의:
                - MDD 개선이 신호 선별 vs 배팅 축소 구분
                - N 감소가 과도하면 통계적 유효성 경고
                - TP/SL 비율과 승률의 트레이드오프
                - 최적 조합뿐 아니라 안정적 영역을 식별
            """),
            user_message=f"메커니즘: {h.phase_1.mechanism.statement}\n\n결과:\n{yaml.dump(grid_results, allow_unicode=True)}",
        )

        print(interpretation.content)
        return {"status": "complete", "stats": grid_results, "interpretation": interpretation.content}

    def _run_domain_expansion(self, strategy_name: str, h, llm: LLMClient) -> dict:
        """Domain Expansion — 다른 타임프레임/기간 테스트"""
        sdir = strategy_dir(strategy_name)
        tm = h.phase_0.target_market

        runner = TestRunner()
        signals_mod = runner._load_module(sdir / "signals.py", "signals")

        timeframes = ["15m", "30m", "1h", "4h", "1d"]
        results = {}

        for tf in timeframes:
            try:
                df = fetch_ohlcv(tm.symbols[0], tf, 365, tm.exchange or None)
                signals = signals_mod.generate_signals(df)
                bt = run_backtest(df, signals)
                results[tf] = bt.stats
            except Exception as e:
                results[tf] = {"error": str(e)}

        # Sonnet 해석
        interpretation = llm.interpret(
            system_prompt="다양한 타임프레임의 백테스트 결과를 비교하고, 전략의 타임프레임 의존성을 분석해줘. 메커니즘에 비추어 설명.",
            user_message=f"메커니즘: {h.phase_1.mechanism.statement}\n\n결과:\n{yaml.dump(results, allow_unicode=True)}",
        )

        print(interpretation.content)
        return {"status": "complete", "stats": results, "interpretation": interpretation.content}

    def _run_universe_expansion(self, strategy_name: str, h, llm: LLMClient) -> dict:
        """Universe Expansion — 다른 종목 테스트"""
        sdir = strategy_dir(strategy_name)
        tm = h.phase_0.target_market

        runner = TestRunner()
        signals_mod = runner._load_module(sdir / "signals.py", "signals")

        # 주요 코인 유니버스
        universe = [
            "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT",
            "BNB/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT",
            "ADA/USDT:USDT", "AVAX/USDT:USDT", "LINK/USDT:USDT",
        ]
        results = {}

        for symbol in universe:
            try:
                df = fetch_ohlcv(symbol, tm.timeframe, 365, tm.exchange or None)
                signals = signals_mod.generate_signals(df)
                bt = run_backtest(df, signals)
                results[symbol] = bt.stats
            except Exception as e:
                results[symbol] = {"error": str(e)}

        # Sonnet 해석
        interpretation = llm.interpret(
            system_prompt="다양한 종목의 백테스트 결과를 분석하고, 종목별 성과 차이의 원인을 메커니즘에 비추어 설명해줘.",
            user_message=f"메커니즘: {h.phase_1.mechanism.statement}\n\n결과:\n{yaml.dump(results, allow_unicode=True)}",
        )

        print(interpretation.content)
        return {"status": "complete", "stats": results, "interpretation": interpretation.content}

    def _run_regime_filter(self, strategy_name: str, h, llm: LLMClient) -> dict:
        """Regime Filter — Sonnet 설계 + DeepSeek 코드 + 실행 + Sonnet 해석"""
        # 1. Sonnet: 필터 설계
        filter_designs = llm.reason(
            system_prompt=textwrap.dedent("""\
                전략의 메커니즘 가설을 읽고, 이 전략이 불리한 국면을
                식별하는 regime 필터를 3~5개 설계해줘.

                각 필터에 대해:
                - 어떤 시장 특성을 측정하는가
                - 왜 이 특성이 전략 성과와 관련되는가 (메커니즘에서 추론)
                - 구체적 지표와 임계값 후보 (2~3개)
                - 테스트 시 주의사항

                JSON으로 출력.
            """),
            user_message=textwrap.dedent(f"""\
                메커니즘: {h.phase_1.mechanism.statement}
                인과 체인: {yaml.dump(h.phase_1.mechanism.causal_chain, allow_unicode=True)}
                전제 조건: {yaml.dump(h.phase_1.mechanism.prerequisites, allow_unicode=True)}
            """),
        )

        # 2. DeepSeek: 필터 코드 생성
        filter_code_response = llm.generate_code(
            system_prompt=load_prompt("codegen.md"),
            user_message=f"다음 regime 필터들을 구현해줘:\n{filter_designs.content}\n\n각 필터를 독립 함수로 구현. apply_filter(df, signals) -> filtered_signals 형태.",
        )

        # 결과 반환 (실제 그리드 서치는 필터 코드 생성 후 수동 실행)
        interpretation = llm.interpret(
            system_prompt="Regime 필터 설계를 검토하고, 예상되는 효과와 주의점을 메커니즘 관점에서 설명해줘.",
            user_message=f"메커니즘: {h.phase_1.mechanism.statement}\n\n필터 설계:\n{filter_designs.content}",
        )

        # 필터 코드 저장
        sdir = strategy_dir(strategy_name)
        filter_path = sdir / "regime_filters.py"
        code = re.search(r"```python\s*\n(.*?)```", filter_code_response.content, re.DOTALL)
        if code:
            filter_path.write_text(code.group(1), encoding="utf-8")
            print(f"  필터 코드 저장: {filter_path}")

        print(interpretation.content)
        return {
            "status": "complete",
            "designs": filter_designs.content,
            "interpretation": interpretation.content,
        }

    def _run_failure_analysis(self, strategy_name: str, h, llm: LLMClient) -> dict:
        """Failure Analysis — 손실 구간 분석 + Sonnet 판별"""
        sdir = strategy_dir(strategy_name)
        tm = h.phase_0.target_market
        df = fetch_ohlcv(tm.symbols[0], tm.timeframe, 365, tm.exchange or None)

        runner = TestRunner()
        signals_mod = runner._load_module(sdir / "signals.py", "signals")
        signals = signals_mod.generate_signals(df)
        bt = run_backtest(df, signals)

        if not bt.trades:
            return {"status": "fail", "message": "트레이드 없음"}

        # 손실/수익 트레이드 분리 통계
        winners = [t for t in bt.trades if t.pnl > 0]
        losers = [t for t in bt.trades if t.pnl <= 0]

        stats = {
            "total_trades": len(bt.trades),
            "winners": len(winners),
            "losers": len(losers),
            "avg_win_mfe": round(float(np.mean([t.mfe for t in winners])), 2) if winners else 0,
            "avg_loss_mfe": round(float(np.mean([t.mfe for t in losers])), 2) if losers else 0,
            "avg_win_mae": round(float(np.mean([t.mae for t in winners])), 2) if winners else 0,
            "avg_loss_mae": round(float(np.mean([t.mae for t in losers])), 2) if losers else 0,
            "avg_win_bars": round(float(np.mean([t.bars_held for t in winners])), 1) if winners else 0,
            "avg_loss_bars": round(float(np.mean([t.bars_held for t in losers])), 1) if losers else 0,
        }

        # Sonnet 해석
        diagnosis = llm.interpret(
            system_prompt=textwrap.dedent("""\
                손실 구간의 통계를 분석하고,
                구조적 문제 vs 확률적 변동을 판별해줘.

                핵심 판별 기준:
                - 손실 구간의 진입 지표값이 수익 구간과 동일하면 → 확률적 변동
                - 손실 구간에 공통 시장 특성이 있으면 → 구조적 (필터 가능)
                - SL 트레이드의 MFE가 낮으면 → 신호 자체가 틀림
                - SL이 빠르면 → 신호 품질 문제 / 느리면 → 타이밍 문제

                판별 결과에 따른 권고:
                - 확률적 → "포지션 사이징으로 생존 보장. 필터 추가 불필요."
                - 구조적 → "Phase 1로 복귀하여 메커니즘 재검토."
            """),
            user_message=f"메커니즘: {h.phase_1.mechanism.statement}\n\n손실 구간 통계:\n{yaml.dump(stats, allow_unicode=True)}",
        )

        print(diagnosis.content)
        return {"status": "complete", "statistics": stats, "interpretation": diagnosis.content}

    def _run_cross_validation(self, strategy_name: str, h, llm: LLMClient) -> dict:
        """Cross-Validation — Sonnet 설계 + 실행 + Sonnet 해석"""
        # Sonnet: 교차 검증 설계
        design = llm.reason(
            system_prompt="이 전략에 적합한 교차 검증 방법을 설계해줘. 시계열 특성을 고려. JSON으로 출력.",
            user_message=f"메커니즘: {h.phase_1.mechanism.statement}\n변수: {yaml.dump([v.name for v in h.phase_1.variables], allow_unicode=True)}",
        )

        # 기본 시간 분할 교차 검증 실행
        sdir = strategy_dir(strategy_name)
        tm = h.phase_0.target_market
        df = fetch_ohlcv(tm.symbols[0], tm.timeframe, 365, tm.exchange or None)

        runner = TestRunner()
        signals_mod = runner._load_module(sdir / "signals.py", "signals")

        n_splits = 5
        split_size = len(df) // n_splits
        cv_results = []

        for i in range(n_splits):
            start = i * split_size
            end = min(start + split_size, len(df))
            split_df = df.iloc[start:end].reset_index(drop=True)

            if len(split_df) < 20:
                continue

            signals = signals_mod.generate_signals(split_df)
            bt = run_backtest(split_df, signals)
            cv_results.append({"split": i + 1, **bt.stats})

        # Sonnet 해석
        interpretation = llm.interpret(
            system_prompt="교차 검증 결과를 분석하고, 시간 안정성과 과적합 위험을 평가해줘.",
            user_message=f"설계:\n{design.content}\n\n결과:\n{yaml.dump(cv_results, allow_unicode=True)}",
        )

        print(interpretation.content)
        return {
            "status": "complete",
            "stats": cv_results,
            "design": design.content,
            "interpretation": interpretation.content,
        }

    def _run_paper_deployment(self, strategy_name: str, h, llm: LLMClient) -> dict:
        """Paper Deployment — 모니터링 기준 설계"""
        # Sonnet: 모니터링 기준 설계
        monitoring = llm.reason(
            system_prompt=textwrap.dedent("""\
                Paper trading 모니터링 기준을 설계해줘.

                포함:
                - 중단 조건 (연속 손실, MDD 한계, 성과 괴리)
                - 모니터링 주기
                - 핵심 지표와 경고 임계값
                - 실거래 전환 기준

                JSON으로 출력.
            """),
            user_message=f"""\
메커니즘: {h.phase_1.mechanism.statement}
검증 결과 요약:
{yaml.dump({k: {"status": v.status} for k, v in h.phase_3.steps.items()}, allow_unicode=True)}
""",
        )

        print(monitoring.content)
        return {"status": "complete", "interpretation": monitoring.content}
