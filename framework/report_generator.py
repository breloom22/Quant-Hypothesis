"""Phase 4 보고서 자동 생성 — DeepSeek 초안 + Sonnet 해석"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from .hypothesis_manager import load_hypothesis, save_hypothesis, load_prompt, strategy_dir
from .llm.client import LLMClient, load_config


def generate_report(strategy_name: str) -> None:
    h = load_hypothesis(strategy_name)
    config = load_config()
    llm = LLMClient(config)

    sdir = strategy_dir(strategy_name)
    results_dir = sdir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    hypothesis_dump = yaml.dump(h.to_dict(), allow_unicode=True, default_flow_style=False)

    # 1. DeepSeek: 정형 섹션 생성
    print("보고서 초안 생성 중 (DeepSeek)...")
    structured = llm.analyze(
        system_prompt=load_prompt("phase4_report.md"),
        user_message=f"""\
다음 hypothesis.yaml에서 리서치 로그를 생성해줘.

{hypothesis_dump}

포함할 섹션:
- 전략 원리
- 파라미터 테이블
- 검증 결과 테이블
- 기각된 것들 테이블
- 메커니즘 변경 이력
- 예측 및 결과
- 검증 파이프라인 각 단계 결과
- 적용 도메인
""",
    )

    # 2. Sonnet: 핵심 발견 + 구조적 한계 해석
    print("핵심 발견 해석 추가 중 (Sonnet)...")
    insights = llm.interpret(
        system_prompt="""\
리서치 로그의 초안을 읽고, 다음을 추가해줘:

1. 핵심 발견 요약 (프로젝트에서 가장 중요한 3가지 발견)
2. 구조적 한계 (이 전략이 본질적으로 약한 영역과 이유)
3. 반증 조건 (이 전략을 폐기해야 할 때)
4. 각 기각된 시도에서 배운 것의 요약
""",
        user_message=structured.content,
    )

    # 3. 결합 + 저장
    full_report = f"""\
# Research Log: {h.strategy_name}

Generated: {datetime.now().isoformat(timespec='seconds')}
Status: {h.status}
Mechanism Version: v{h.phase_1.mechanism.version}

---

{structured.content}

---

## Key Insights & Limitations

{insights.content}
"""

    report_path = sdir / "log.md"
    report_path.write_text(full_report, encoding="utf-8")
    print(f"보고서 저장: {report_path}")

    # 4. 요약본 생성 (DeepSeek)
    print("요약본 생성 중 (DeepSeek)...")
    summary = llm.analyze(
        system_prompt="위 리서치 로그를 150줄 이내로 요약해줘. 핵심 수치와 결론 위주.",
        user_message=full_report,
    )

    summary_path = sdir / "summary.md"
    summary_path.write_text(
        f"# Summary: {h.strategy_name}\n\n{summary.content}",
        encoding="utf-8",
    )
    print(f"요약본 저장: {summary_path}")

    # 메타데이터 업데이트
    h.phase_4.report_path = str(report_path)
    h.phase_4.summary_path = str(summary_path)
    h.phase_4.generated_at = datetime.now().isoformat(timespec="seconds")
    h.llm_cost = {k: h.llm_cost.get(k, 0) + llm.usage.get(k, 0) for k in llm.usage}
    save_hypothesis(h)

    cost = llm.get_cost_summary()
    print(f"\n보고서 생성 비용: ${cost['total_cost_usd']:.4f}")
    print("완료!")
