"""Phase 2 정제 루프 — LLM 기반 해석 + 제안"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import yaml

from .hypothesis_manager import load_hypothesis, save_hypothesis, load_prompt, strategy_dir
from .llm.client import LLMClient, load_config
from .schema import RefinementEntry, Prediction
from .test_runner import TestRunner


class RefinementLoop:
    """실패한 예측을 해석하고, 분리 테스트를 설계/실행하고, 가설을 수정한다."""

    def run_loop(self, strategy_name: str, auto: bool = False) -> dict:
        """test→refine을 전체 통과 또는 max_refinements까지 자동 반복.

        Returns:
            요약 dict: refinement_count, max_refinements, passed, failed, total
        """
        h = load_hypothesis(strategy_name)
        max_ref = h.phase_2.max_refinements

        for i in range(max_ref + 1):
            h = load_hypothesis(strategy_name)
            runner = TestRunner()

            # 테스트 실행
            print(f"\n--- 테스트 실행 (반복 {i + 1}/{max_ref + 1}) ---")
            runner.run_all(strategy_name)
            h = load_hypothesis(strategy_name)

            # 통과/실패 집계
            passed = [p for p in h.phase_1.predictions if p.status == "pass"]
            failed = [p for p in h.phase_1.predictions if p.status != "pass"]
            total = len(h.phase_1.predictions)

            if not failed:
                print("모든 예측 통과!")
                break

            if h.phase_2.refinement_count >= max_ref:
                print(f"최대 정제 횟수 ({max_ref})에 도달했습니다.")
                break

            # refine 1회 실행
            print(f"\n--- 정제 루프 ({h.phase_2.refinement_count + 1}/{max_ref}) ---")
            self.run(strategy_name, auto=auto)

        # 최종 상태 로드
        h = load_hypothesis(strategy_name)
        passed = [p for p in h.phase_1.predictions if p.status == "pass"]
        failed = [p for p in h.phase_1.predictions if p.status != "pass"]
        total = len(h.phase_1.predictions)

        return {
            "refinement_count": h.phase_2.refinement_count,
            "max_refinements": max_ref,
            "passed": len(passed),
            "failed": len(failed),
            "failed_ids": [p.id for p in failed],
            "total": total,
        }

    def run(self, strategy_name: str, auto: bool = False) -> None:
        h = load_hypothesis(strategy_name)
        config = load_config()
        llm = LLMClient(config)
        runner = TestRunner()

        # 정제 횟수 체크
        if h.phase_2.refinement_count >= h.phase_2.max_refinements:
            print(f"최대 정제 횟수 ({h.phase_2.max_refinements})에 도달했습니다.")
            print("가설 폐기를 고려해주세요.")
            return

        # 1. 전체 예측 테스트 실행
        print("예측 테스트 실행 중...")
        test_results = runner.run_all(strategy_name)
        h = load_hypothesis(strategy_name)  # 테스트 결과 반영된 것 다시 로드

        # 2. 통과/실패 판정 (DeepSeek)
        print("결과 판정 중 (DeepSeek)...")
        judgments_response = llm.analyze(
            system_prompt="""\
각 예측 테스트의 결과를 보고 통과/실패를 판정해줘.
각 예측의 success_condition과 실제 값을 비교.
출력: JSON 배열. 각 원소: {"prediction_id": "...", "pass": true/false, "reason": "..."}
""",
            user_message=yaml.dump(test_results, allow_unicode=True),
        )

        judgments = self._parse_json(judgments_response.content)
        failed = [j for j in judgments if not j.get("pass", False)]

        if not failed:
            print("모든 예측 통과! Phase 3으로 진행 가능합니다.")
            return

        print(f"\n실패한 예측: {len(failed)}개")
        for f in failed:
            print(f"  - {f.get('prediction_id', '?')}: {f.get('reason', '')}")

        # 3. 실패 해석 (Sonnet)
        print("\n실패 해석 중 (Sonnet)...")
        interpretation_response = llm.interpret(
            system_prompt=load_prompt("phase2_refinement.md"),
            user_message=f"""\
다음 예측이 실패했다:
{yaml.dump(failed, allow_unicode=True)}

현재 메커니즘 가설 (v{h.phase_1.mechanism.version}):
{h.phase_1.mechanism.statement}

전제 조건:
{yaml.dump(h.phase_1.mechanism.prerequisites, allow_unicode=True)}

인과 체인:
{yaml.dump(h.phase_1.mechanism.causal_chain, allow_unicode=True)}

각 변수의 정의와 후보:
{yaml.dump([v.__dict__ for v in h.phase_1.variables], allow_unicode=True)}

1. 이 실패가 메커니즘의 어떤 전제를 반증하는지 분석
2. 원인 후보 2~3개를 나열하고 각각을 검증하는 분리 테스트 설계
3. 각 분리 테스트의 결과별 의미를 사전 정의
""",
        )

        print("\n" + "=" * 60)
        print("  실패 해석 (Sonnet)")
        print("=" * 60)
        print(interpretation_response.content)

        # 4. 사람 승인
        if auto:
            action = "y"
            print("\n[auto] 분리 테스트 자동 승인")
        else:
            action = input("\n분리 테스트를 진행할까요? [y/n]: ").strip().lower()
        if action != "y":
            print("정제 루프 중단.")
            return

        # 5. 분리 테스트 코드 생성 (DeepSeek)
        print("\n분리 테스트 코드 생성 중 (DeepSeek)...")
        isolation_tests = self._extract_test_designs(interpretation_response.content)

        sdir = strategy_dir(strategy_name)
        signals_code = (sdir / "signals.py").read_text(encoding="utf-8") if (sdir / "signals.py").exists() else ""
        tests_dir = sdir / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)

        for test in isolation_tests:
            code_response = llm.generate_code(
                system_prompt=load_prompt("codegen.md"),
                user_message=f"""\
다음 분리 테스트를 구현해줘:
{test.get('description', '')}

기존 signals.py의 overrides 패턴을 사용.
변경할 변수: {test.get('variable', '')}
교체할 구현: {test.get('candidate', '')}

테스트 함수명: run_test()
결과: dict 반환 (passed: bool, stats: dict, description: str)
""",
                context=signals_code,
            )

            code = self._extract_code(code_response.content)
            test_id = test.get("id", f"isolation_{test.get('variable', 'unknown')}")
            test_path = tests_dir / f"test_{test_id}.py"
            test_path.write_text(code, encoding="utf-8")
            print(f"  생성: {test_path}")

        # 6. 분리 테스트 실행
        print("\n분리 테스트 실행 중...")
        isolation_results = {}
        for test in isolation_tests:
            test_id = test.get("id", f"isolation_{test.get('variable', 'unknown')}")
            result = runner._execute_test_file(tests_dir / f"test_{test_id}.py")
            isolation_results[test_id] = result
            status = "PASS" if result.get("passed") else "FAIL"
            print(f"  [{status}] {test_id}")

        # 7. 결과 해석 + 가설 수정 제안 (Sonnet)
        print("\n가설 수정 제안 생성 중 (Sonnet)...")
        revision_response = llm.interpret(
            system_prompt=load_prompt("phase2_refinement.md"),
            user_message=f"""\
분리 테스트 결과:
{yaml.dump(isolation_results, allow_unicode=True)}

현재 메커니즘 (v{h.phase_1.mechanism.version}):
{h.phase_1.mechanism.statement}

1. 어떤 원인이 확인되었는가
2. 메커니즘을 어떻게 수정해야 하는가 (v{h.phase_1.mechanism.version + 1})
3. 수정된 가설에서 파생되는 새로운 예측 2~3개
""",
        )

        print("\n" + "=" * 60)
        print("  가설 수정 제안 (Sonnet)")
        print("=" * 60)
        print(revision_response.content)

        # 8. 사람 승인 → YAML 업데이트
        if auto:
            action = "a"
            print("\n[auto] 가설 수정 자동 수락")
        else:
            action = input("\n이 수정을 적용할까요? [a]ccept / [e]dit / [r]eject: ").strip().lower()
        if action == "a":
            self._apply_revision(h, revision_response.content, failed)
            h.llm_cost = {
                k: h.llm_cost.get(k, 0) + llm.usage.get(k, 0)
                for k in llm.usage
            }
            save_hypothesis(h)
            print("가설 수정 적용 완료.")
            cost = llm.get_cost_summary()
            print(f"이번 정제 비용: ${cost['total_cost_usd']:.4f}")
        elif action == "r":
            print("수정 거부. 정제 루프 종료.")
        else:
            print("수동 편집이 필요합니다. hypothesis.yaml을 직접 수정해주세요.")

    def _apply_revision(self, h, revision_text: str, failed: list) -> None:
        """가설 수정 적용"""
        h.phase_2.refinement_count += 1

        entry = RefinementEntry(
            version=h.phase_1.mechanism.version + 1,
            failed_predictions=[f.get("prediction_id", "") for f in failed],
            interpretation=revision_text,
            timestamp=datetime.now().isoformat(timespec="seconds"),
        )
        h.phase_2.refinement_history.append(entry)

        # 메커니즘 버전 업
        h.phase_1.mechanism.version += 1

        # YAML에서 새 메커니즘/예측 파싱 시도
        parsed = self._parse_yaml_block(revision_text)
        if parsed:
            if "mechanism" in parsed:
                mech = parsed["mechanism"]
                if isinstance(mech, dict):
                    h.phase_1.mechanism.statement = mech.get("statement", h.phase_1.mechanism.statement)
                    if "prerequisites" in mech:
                        h.phase_1.mechanism.prerequisites = mech["prerequisites"]
                    if "causal_chain" in mech:
                        h.phase_1.mechanism.causal_chain = mech["causal_chain"]
                    if "falsification" in mech:
                        h.phase_1.mechanism.falsification = mech["falsification"]
            if "new_predictions" in parsed:
                for p in parsed["new_predictions"]:
                    if isinstance(p, dict):
                        h.phase_1.predictions.append(Prediction(
                            id=p.get("id", f"pred_r{h.phase_2.refinement_count}_{len(h.phase_1.predictions)}"),
                            statement=p.get("statement", ""),
                            test_type=p.get("test_type", "ab_compare"),
                            success_condition=p.get("success_condition", ""),
                            failure_learning=p.get("failure_learning", ""),
                            priority=p.get("priority", "medium"),
                        ))

    @staticmethod
    def _parse_json(text: str) -> list:
        import json
        match = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
        raw = match.group(1) if match else text
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            return []

    @staticmethod
    def _parse_yaml_block(text: str) -> dict:
        match = re.search(r"```ya?ml\s*\n(.*?)```", text, re.DOTALL)
        if match:
            try:
                return yaml.safe_load(match.group(1)) or {}
            except yaml.YAMLError:
                return {}
        return {}

    @staticmethod
    def _extract_test_designs(text: str) -> list[dict]:
        """LLM 해석에서 분리 테스트 설계 추출"""
        parsed = RefinementLoop._parse_yaml_block(text)
        if parsed and "isolation_tests" in parsed:
            return parsed["isolation_tests"]

        # YAML 없으면 구조적 패턴 매칭 시도
        tests = []
        pattern = re.compile(
            r"(?:테스트|test)\s*(?:\d+|[A-Za-z])[\s:.\-]*(.+?)(?=(?:테스트|test)\s*(?:\d+|[A-Za-z])|$)",
            re.DOTALL | re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            desc = match.group(1).strip()[:200]
            tests.append({
                "id": f"isolation_{len(tests) + 1}",
                "description": desc,
                "variable": "",
                "candidate": "",
            })
        return tests

    @staticmethod
    def _extract_code(text: str) -> str:
        match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
        return match.group(1) if match else text
