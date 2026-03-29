#!/usr/bin/env python3
"""Quant Hypothesis Framework — CLI 인터페이스"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import datetime

import yaml

from framework.schema import Hypothesis, Status
from framework.hypothesis_manager import (
    create_hypothesis,
    load_hypothesis,
    save_hypothesis,
    update_status,
    list_strategies,
    load_prompt,
    strategy_dir,
)
from framework.llm.client import LLMClient, load_config
from framework.refinement_loop import RefinementLoop
from framework.validation_pipeline import ValidationPipeline
from framework.report_generator import generate_report


# ── 유틸리티 ─────────────────────────────────────────────────

def _input(prompt: str, default: str = "") -> str:
    val = input(prompt).strip()
    return val if val else default


def _print_section(title: str, content: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    print(content)
    print()


def _parse_yaml_from_response(text: str) -> dict:
    """LLM 응답에서 YAML 블록 추출"""
    import re
    match = re.search(r"```ya?ml\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return yaml.safe_load(match.group(1))
    # YAML 블록 마커 없으면 전체를 시도
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return {}


def _extract_code_block(text: str) -> str:
    """LLM 응답에서 Python 코드 블록 추출"""
    import re
    match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1)
    return text


# ── run: end-to-end 실행 ─────────────────────────────────────

def _run_phase1(name: str, auto: bool = False) -> dict:
    """Phase 1 구조화 실행. 요약 dict 반환."""
    h = load_hypothesis(name)
    config = load_config()
    llm = LLMClient(config)

    h.status = Status.PHASE_1_STRUCTURING.value
    save_hypothesis(h)

    # Sonnet 구조화
    response = llm.reason(
        system_prompt=load_prompt("phase1_structuring.md"),
        user_message=textwrap.dedent(f"""\
            다음 트레이딩 직관을 구조화해줘.

            관찰: {h.phase_0.observation}
            기대: {h.phase_0.expectation}
            빈도: {h.phase_0.frequency_sense}
            시장: {yaml.dump(h.phase_0.target_market.__dict__, allow_unicode=True)}
        """),
    )

    _print_section("Sonnet의 구조화 제안", response.content)

    if not auto:
        while True:
            action = _input("[a]ccept / [e]dit / [r]egenerate: ")
            if action == "a":
                break
            elif action == "e":
                feedback = _input("수정 사항: ")
                response = llm.reason(
                    system_prompt=load_prompt("phase1_structuring.md"),
                    user_message=f"이전 제안을 다음과 같이 수정해줘:\n{feedback}",
                    context=response.content,
                )
                _print_section("수정된 제안", response.content)
            elif action == "r":
                response = llm.reason(
                    system_prompt=load_prompt("phase1_structuring.md"),
                    user_message="다른 관점에서 다시 구조화해줘.",
                    context=yaml.dump(h.phase_0.__dict__, allow_unicode=True),
                )
                _print_section("새로운 제안", response.content)
    else:
        print("[auto] 첫 번째 제안 자동 수락")

    # YAML 파싱 + Phase 1 저장
    phase_1_data = _parse_yaml_from_response(response.content)
    if phase_1_data:
        from framework.schema import Variable, VariableCandidate, Prediction
        h.phase_1.variables = []
        for v in phase_1_data.get("variables", []):
            candidates = [VariableCandidate(**c) for c in v.get("candidates", [])]
            h.phase_1.variables.append(Variable(
                name=v.get("name", ""),
                role=v.get("role", ""),
                initial_implementation=v.get("initial_implementation", ""),
                initial_reason=v.get("initial_reason", ""),
                candidates=candidates,
            ))
        mech = phase_1_data.get("mechanism", {})
        if mech:
            h.phase_1.mechanism.statement = mech.get("statement", "")
            h.phase_1.mechanism.prerequisites = mech.get("prerequisites", [])
            h.phase_1.mechanism.causal_chain = mech.get("causal_chain", [])
            h.phase_1.mechanism.falsification = mech.get("falsification", [])
        h.phase_1.predictions = []
        for p in phase_1_data.get("predictions", []):
            h.phase_1.predictions.append(Prediction(
                id=p.get("id", ""),
                statement=p.get("statement", ""),
                test_type=p.get("test_type", ""),
                success_condition=p.get("success_condition", ""),
                failure_learning=p.get("failure_learning", ""),
                priority=p.get("priority", "medium"),
            ))

    h.status = Status.PHASE_1_COMPLETE.value
    save_hypothesis(h)
    print("Phase 1 데이터 저장 완료.")

    # 코드 생성
    _generate_signal_code(name, h, llm)
    _generate_test_code(name, h, llm)

    h.llm_cost = {k: h.llm_cost.get(k, 0) + llm.usage.get(k, 0) for k in llm.usage}
    save_hypothesis(h)

    cost = llm.get_cost_summary()
    return {
        "mechanism": h.phase_1.mechanism.statement,
        "n_variables": len(h.phase_1.variables),
        "n_predictions": len(h.phase_1.predictions),
        "cost_usd": cost["total_cost_usd"],
    }


def _run_phase2(name: str, auto: bool = False) -> dict:
    """Phase 2 테스트+정제 루프 실행. 요약 dict 반환."""
    h = load_hypothesis(name)
    h.status = Status.PHASE_2_REFINEMENT.value
    save_hypothesis(h)

    loop = RefinementLoop()
    summary = loop.run_loop(name, auto=auto)

    h = load_hypothesis(name)
    h.status = Status.PHASE_2_COMPLETE.value
    save_hypothesis(h)

    return summary


def _run_phase3(name: str, auto: bool = False) -> dict:
    """Phase 3 검증 파이프라인 실행. 요약 dict 반환."""
    h = load_hypothesis(name)
    h.status = Status.PHASE_3_VALIDATION.value
    save_hypothesis(h)

    pipeline = ValidationPipeline()
    summary = pipeline.run_all(name, auto=auto)

    h = load_hypothesis(name)
    h.status = Status.PHASE_3_COMPLETE.value
    save_hypothesis(h)

    return summary


def _run_phase4(name: str) -> dict:
    """Phase 4 보고서 생성. 요약 dict 반환."""
    h = load_hypothesis(name)
    h.status = Status.PHASE_4_REPORT.value
    save_hypothesis(h)

    generate_report(name)

    h = load_hypothesis(name)
    h.status = Status.COMPLETE.value
    save_hypothesis(h)

    return {
        "report_path": h.phase_4.report_path,
        "summary_path": h.phase_4.summary_path,
    }


def _print_phase_summary(title: str, summary: dict) -> None:
    """Phase 완료 요약 출력."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    for k, v in summary.items():
        if k == "mechanism":
            print(f"  메커니즘: {str(v)[:80]}")
        elif k == "cost_usd":
            print(f"  비용: ${v:.4f}")
        elif k == "failed_steps":
            if v:
                print(f"  실패 단계: {', '.join(v)}")
        elif k == "failed_ids":
            if v:
                print(f"  실패 예측: {', '.join(v)}")
        else:
            print(f"  {k}: {v}")
    print(f"{'='*60}")


def cmd_run(args: argparse.Namespace) -> None:
    """Phase 1~4 end-to-end 실행."""
    name = args.strategy_name
    auto = args.auto

    h = load_hypothesis(name)
    if not h.phase_0.observation:
        print("Phase 0이 완료되지 않았습니다. 먼저 'python cli.py new' 를 실행하세요.")
        return

    # ── Phase 1 ──
    print(f"\n{'#'*60}")
    print(f"  Phase 1: 구조화")
    print(f"{'#'*60}")
    summary1 = _run_phase1(name, auto=auto)

    if not auto:
        _print_phase_summary("Phase 1 완료 — 구조화", summary1)
        action = _input("[n]ext / [r]etry / [a]bort: ")
        while action == "r":
            summary1 = _run_phase1(name, auto=False)
            _print_phase_summary("Phase 1 완료 — 구조화", summary1)
            action = _input("[n]ext / [r]etry / [a]bort: ")
        if action == "a":
            print("중단.")
            return

    # ── Phase 2 ──
    print(f"\n{'#'*60}")
    print(f"  Phase 2: 테스트/정제")
    print(f"{'#'*60}")
    summary2 = _run_phase2(name, auto=auto)

    if not auto:
        _print_phase_summary("Phase 2 완료 — 테스트/정제", summary2)
        action = _input("[n]ext / [r]etry / [a]bort: ")
        while action == "r":
            summary2 = _run_phase2(name, auto=False)
            _print_phase_summary("Phase 2 완료 — 테스트/정제", summary2)
            action = _input("[n]ext / [r]etry / [a]bort: ")
        if action == "a":
            print("중단.")
            return

    # ── Phase 3 ──
    print(f"\n{'#'*60}")
    print(f"  Phase 3: 검증")
    print(f"{'#'*60}")
    summary3 = _run_phase3(name, auto=auto)

    if not auto:
        _print_phase_summary("Phase 3 완료 — 검증", summary3)
        action = _input("[n]ext / [r]etry / [a]bort: ")
        while action == "r":
            summary3 = _run_phase3(name, auto=False)
            _print_phase_summary("Phase 3 완료 — 검증", summary3)
            action = _input("[n]ext / [r]etry / [a]bort: ")
        if action == "a":
            print("중단.")
            return

    # ── Phase 4 ──
    print(f"\n{'#'*60}")
    print(f"  Phase 4: 보고서")
    print(f"{'#'*60}")
    summary4 = _run_phase4(name)

    # ── 최종 요약 ──
    h = load_hypothesis(name)
    cost = h.llm_cost
    sonnet_cost = (cost["sonnet_input_tokens"] / 1e6 * 3.0
                   + cost["sonnet_output_tokens"] / 1e6 * 15.0)
    deepseek_cost = (cost["deepseek_input_tokens"] / 1e6 * 0.28
                     + cost["deepseek_output_tokens"] / 1e6 * 0.42)

    print(f"\n{'#'*60}")
    print(f"  전체 파이프라인 완료!")
    print(f"{'#'*60}")
    print(f"  전략: {name}")
    print(f"  상태: {h.status}")
    print(f"  보고서: {summary4.get('report_path', '')}")
    print(f"  요약본: {summary4.get('summary_path', '')}")
    print(f"  총 비용: ${sonnet_cost + deepseek_cost:.4f}")
    print(f"{'#'*60}")


# ── Phase 0: new ─────────────────────────────────────────────

def cmd_new(args: argparse.Namespace) -> None:
    """새 전략 가설 생성"""
    name = args.strategy_name

    h = create_hypothesis(name)
    sdir = strategy_dir(name)

    print(f"전략 '{name}' 생성 완료: {sdir}")
    print()

    # Phase 0 입력
    print("--- Phase 0: 트레이딩 직관 입력 ---")
    h.phase_0.observation = _input("관찰 (패턴/현상): ")
    h.phase_0.expectation = _input("기대 (어떤 결과를 예상하는가): ")
    h.phase_0.frequency_sense = _input("빈도 감각 (얼마나 자주 발생하는가): ")

    print()
    print("--- 대상 시장 ---")
    h.phase_0.target_market.exchange = _input("거래소 [binanceusdm]: ", "binanceusdm")
    symbols_raw = _input("종목 (쉼표 구분) [BTC/USDT:USDT]: ", "BTC/USDT:USDT")
    h.phase_0.target_market.symbols = [s.strip() for s in symbols_raw.split(",")]
    h.phase_0.target_market.timeframe = _input("타임프레임 [1h]: ", "1h")
    h.phase_0.target_market.data_source = _input("데이터 소스 [ccxt]: ", "ccxt")

    save_hypothesis(h)
    print(f"\nPhase 0 완료. 다음: python cli.py structure \"{name}\"")


# ── Phase 1: structure ───────────────────────────────────────

def cmd_structure(args: argparse.Namespace) -> None:
    """LLM 대화형 구조화 세션"""
    name = args.strategy_name
    summary = _run_phase1(name, auto=False)
    _print_phase_summary("Phase 1 완료 — 구조화", summary)
    print(f"다음: python cli.py test \"{name}\"")


def _generate_signal_code(name: str, h: Hypothesis, llm: LLMClient) -> None:
    """DeepSeek으로 signals.py 생성"""
    response = llm.generate_code(
        system_prompt=load_prompt("codegen.md"),
        user_message=textwrap.dedent(f"""\
            다음 변수 정의에 따라 signals.py를 생성해줘.

            전략명: {h.strategy_name}
            대상 시장: {yaml.dump(h.phase_0.target_market.__dict__, allow_unicode=True)}
            변수 정의:
            {yaml.dump([v.__dict__ for v in h.phase_1.variables], allow_unicode=True)}
        """),
    )

    code = _extract_code_block(response.content)
    out_path = strategy_dir(name) / "signals.py"
    out_path.write_text(code, encoding="utf-8")
    print(f"signals.py 생성 완료: {out_path}")
    print("코드를 검수해주세요.")


def _generate_test_code(name: str, h: Hypothesis, llm: LLMClient) -> None:
    """DeepSeek으로 예측 테스트 코드 생성"""
    if not h.phase_1.predictions:
        return

    tests_dir = strategy_dir(name) / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    for pred in h.phase_1.predictions:
        response = llm.generate_code(
            system_prompt=load_prompt("codegen.md"),
            user_message=textwrap.dedent(f"""\
                다음 예측을 검증하는 테스트 코드를 작성해줘.

                예측 ID: {pred.id}
                서술: {pred.statement}
                테스트 유형: {pred.test_type}
                성공 기준: {pred.success_condition}

                signals.py의 generate_signals() 함수와 overrides 패턴을 사용.
                backtest_engine.run()으로 백테스트 실행.
                결과를 JSON으로 출력.
            """),
        )

        code = _extract_code_block(response.content)
        test_path = tests_dir / f"test_{pred.id}.py"
        test_path.write_text(code, encoding="utf-8")
        print(f"  테스트 생성: {test_path}")


# ── Phase 2: test / refine ───────────────────────────────────

def cmd_test(args: argparse.Namespace) -> None:
    """예측 테스트 실행"""
    name = args.strategy_name
    h = load_hypothesis(name)

    from framework.test_runner import TestRunner
    runner = TestRunner()

    if args.pred:
        results = runner.run_single(name, args.pred)
    elif args.isolation:
        results = runner.run_isolation(name, args.isolation)
    else:
        results = runner.run_all(name)

    print(yaml.dump(results, allow_unicode=True, default_flow_style=False))


def cmd_refine(args: argparse.Namespace) -> None:
    """정제 루프 1회 실행"""
    name = args.strategy_name
    loop = RefinementLoop()
    loop.run(name, auto=False)


def cmd_status(args: argparse.Namespace) -> None:
    """전략 상태 표시"""
    name = args.strategy_name
    h = load_hypothesis(name)

    print(f"전략: {h.strategy_name}")
    print(f"상태: {h.status}")
    print(f"생성: {h.created_at}")
    print()

    if h.phase_1.mechanism.statement:
        print(f"메커니즘 (v{h.phase_1.mechanism.version}): {h.phase_1.mechanism.statement}")

    if h.phase_1.predictions:
        print(f"\n예측 ({len(h.phase_1.predictions)}개):")
        for p in h.phase_1.predictions:
            print(f"  [{p.status:^7}] {p.id}: {p.statement[:60]}")

    if h.phase_2.refinement_count > 0:
        print(f"\n정제 횟수: {h.phase_2.refinement_count}/{h.phase_2.max_refinements}")

    if h.phase_3.steps:
        print(f"\n검증 단계:")
        for step_id, step in h.phase_3.steps.items():
            print(f"  [{step.status:^7}] {step_id}")

    # 비용
    cost_data = h.llm_cost
    if any(v > 0 for v in cost_data.values()):
        sonnet_cost = (cost_data["sonnet_input_tokens"] / 1e6 * 3.0
                       + cost_data["sonnet_output_tokens"] / 1e6 * 15.0)
        deepseek_cost = (cost_data["deepseek_input_tokens"] / 1e6 * 0.28
                         + cost_data["deepseek_output_tokens"] / 1e6 * 0.42)
        print(f"\n누적 비용: ${sonnet_cost + deepseek_cost:.4f}")


# ── Phase 3: validate ────────────────────────────────────────

def cmd_validate(args: argparse.Namespace) -> None:
    """검증 파이프라인 실행"""
    name = args.strategy_name
    pipeline = ValidationPipeline()

    if args.step:
        result = pipeline.run_step(name, args.step)
        print(yaml.dump(result, allow_unicode=True, default_flow_style=False))
    else:
        pipeline.run_all(name, auto=False)


# ── Phase 4: report ──────────────────────────────────────────

def cmd_report(args: argparse.Namespace) -> None:
    """리서치 보고서 생성"""
    name = args.strategy_name
    generate_report(name)


# ── 유틸리티 커맨드 ──────────────────────────────────────────

def cmd_list(args: argparse.Namespace) -> None:
    """전략 목록"""
    strategies = list_strategies()
    if not strategies:
        print("등록된 전략이 없습니다.")
        return

    print(f"{'이름':<25} {'상태':<25} {'생성일'}")
    print("-" * 70)
    for s in strategies:
        print(f"{s['name']:<25} {s['status']:<25} {s['created_at']}")


def cmd_cost(args: argparse.Namespace) -> None:
    """LLM API 비용 집계"""
    name = args.strategy_name
    h = load_hypothesis(name)
    cost = h.llm_cost

    sonnet_cost = (cost["sonnet_input_tokens"] / 1e6 * 3.0
                   + cost["sonnet_output_tokens"] / 1e6 * 15.0)
    deepseek_cost = (cost["deepseek_input_tokens"] / 1e6 * 0.28
                     + cost["deepseek_output_tokens"] / 1e6 * 0.42)

    print(f"전략: {name}")
    print(f"Sonnet:   {cost['sonnet_input_tokens']:>8} in + {cost['sonnet_output_tokens']:>8} out = ${sonnet_cost:.4f}")
    print(f"DeepSeek: {cost['deepseek_input_tokens']:>8} in + {cost['deepseek_output_tokens']:>8} out = ${deepseek_cost:.4f}")
    print(f"합계: ${sonnet_cost + deepseek_cost:.4f}")


def cmd_data(args: argparse.Namespace) -> None:
    """데이터 fetch"""
    from framework.data.fetchers import fetch_ohlcv
    symbol = args.symbol
    timeframe = args.timeframe
    days = int(args.days)
    df = fetch_ohlcv(symbol, timeframe, days)
    print(f"Fetched {len(df)} candles for {symbol} {timeframe} ({days}d)")
    print(df.tail())


# ── 메인 파서 ────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Quant Hypothesis Framework",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run (end-to-end)
    p = sub.add_parser("run", help="Phase 1~4 end-to-end 실행")
    p.add_argument("strategy_name")
    p.add_argument("--auto", action="store_true", help="인간 개입 없이 자동 실행")
    p.set_defaults(func=cmd_run)

    # new
    p = sub.add_parser("new", help="새 전략 가설 생성")
    p.add_argument("strategy_name")
    p.set_defaults(func=cmd_new)

    # structure
    p = sub.add_parser("structure", help="LLM 대화형 구조화")
    p.add_argument("strategy_name")
    p.set_defaults(func=cmd_structure)

    # test
    p = sub.add_parser("test", help="예측 테스트 실행")
    p.add_argument("strategy_name")
    p.add_argument("--pred", help="특정 예측 ID")
    p.add_argument("--isolation", help="분리 테스트 변수")
    p.set_defaults(func=cmd_test)

    # refine
    p = sub.add_parser("refine", help="정제 루프 1회")
    p.add_argument("strategy_name")
    p.set_defaults(func=cmd_refine)

    # status
    p = sub.add_parser("status", help="전략 상태")
    p.add_argument("strategy_name")
    p.set_defaults(func=cmd_status)

    # validate
    p = sub.add_parser("validate", help="검증 파이프라인")
    p.add_argument("strategy_name")
    p.add_argument("--step", help="특정 단계")
    p.set_defaults(func=cmd_validate)

    # report
    p = sub.add_parser("report", help="보고서 생성")
    p.add_argument("strategy_name")
    p.set_defaults(func=cmd_report)

    # list
    p = sub.add_parser("list", help="전략 목록")
    p.set_defaults(func=cmd_list)

    # cost
    p = sub.add_parser("cost", help="LLM 비용 집계")
    p.add_argument("strategy_name")
    p.set_defaults(func=cmd_cost)

    # data
    p = sub.add_parser("data", help="데이터 fetch")
    p.add_argument("action", choices=["fetch"])
    p.add_argument("symbol", help="예: BTC/USDT:USDT")
    p.add_argument("timeframe", help="예: 1h")
    p.add_argument("days", help="기간 (일)")
    p.set_defaults(func=cmd_data)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
