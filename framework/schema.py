"""데이터 구조 정의 — hypothesis.yaml의 Python 표현"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class Status(str, Enum):
    PHASE_0_INTAKE = "phase_0_intake"
    PHASE_1_STRUCTURING = "phase_1_structuring"
    PHASE_1_COMPLETE = "phase_1_complete"
    PHASE_2_REFINEMENT = "phase_2_refinement"
    PHASE_2_COMPLETE = "phase_2_complete"
    PHASE_3_VALIDATION = "phase_3_validation"
    PHASE_3_COMPLETE = "phase_3_complete"
    PHASE_4_REPORT = "phase_4_report"
    COMPLETE = "complete"
    ABANDONED = "abandoned"


@dataclass
class TargetMarket:
    exchange: str = ""
    symbols: list[str] = field(default_factory=list)
    timeframe: str = ""
    data_source: str = ""


@dataclass
class Phase0:
    observation: str = ""
    expectation: str = ""
    frequency_sense: str = ""
    target_market: TargetMarket = field(default_factory=TargetMarket)


@dataclass
class VariableCandidate:
    name: str = ""
    reason: str = ""
    expected_if_success: str = ""
    expected_if_failure: str = ""


@dataclass
class Variable:
    name: str = ""
    role: str = ""
    initial_implementation: str = ""
    initial_reason: str = ""
    candidates: list[VariableCandidate] = field(default_factory=list)


@dataclass
class Mechanism:
    statement: str = ""
    prerequisites: list[str] = field(default_factory=list)
    causal_chain: list[str] = field(default_factory=list)
    falsification: list[str] = field(default_factory=list)
    version: int = 1


@dataclass
class Prediction:
    id: str = ""
    statement: str = ""
    test_type: str = ""  # ab_compare / domain_test / property_check
    success_condition: str = ""
    failure_learning: str = ""
    priority: str = "medium"  # high / medium / low
    status: str = "pending"  # pending / pass / fail
    result: dict[str, Any] = field(default_factory=dict)


@dataclass
class Phase1:
    variables: list[Variable] = field(default_factory=list)
    mechanism: Mechanism = field(default_factory=Mechanism)
    predictions: list[Prediction] = field(default_factory=list)


@dataclass
class RefinementEntry:
    version: int = 0
    failed_predictions: list[str] = field(default_factory=list)
    interpretation: str = ""
    isolation_tests: list[dict[str, Any]] = field(default_factory=list)
    revision: str = ""
    new_predictions: list[str] = field(default_factory=list)
    timestamp: str = ""


@dataclass
class Phase2:
    refinement_count: int = 0
    max_refinements: int = 3
    refinement_history: list[RefinementEntry] = field(default_factory=list)


@dataclass
class ValidationStep:
    status: str = "pending"  # pending / running / pass / fail / skip
    result: dict[str, Any] = field(default_factory=dict)
    interpretation: str = ""
    timestamp: str = ""


@dataclass
class Phase3:
    steps: dict[str, ValidationStep] = field(default_factory=dict)


@dataclass
class Phase4:
    report_path: str = ""
    summary_path: str = ""
    generated_at: str = ""


@dataclass
class Hypothesis:
    strategy_name: str = ""
    created_at: str = ""
    status: str = Status.PHASE_0_INTAKE.value

    phase_0: Phase0 = field(default_factory=Phase0)
    phase_1: Phase1 = field(default_factory=Phase1)
    phase_2: Phase2 = field(default_factory=Phase2)
    phase_3: Phase3 = field(default_factory=Phase3)
    phase_4: Phase4 = field(default_factory=Phase4)

    llm_cost: dict[str, float] = field(default_factory=lambda: {
        "sonnet_input_tokens": 0,
        "sonnet_output_tokens": 0,
        "deepseek_input_tokens": 0,
        "deepseek_output_tokens": 0,
    })

    def to_dict(self) -> dict:
        """재귀적으로 dataclass → dict 변환"""
        return _to_dict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Hypothesis:
        """dict → Hypothesis 변환"""
        h = cls()
        h.strategy_name = data.get("strategy_name", "")
        h.created_at = data.get("created_at", "")
        h.status = data.get("status", Status.PHASE_0_INTAKE.value)

        p0 = data.get("phase_0", {})
        if p0:
            tm = p0.get("target_market", {})
            h.phase_0 = Phase0(
                observation=p0.get("observation", ""),
                expectation=p0.get("expectation", ""),
                frequency_sense=p0.get("frequency_sense", ""),
                target_market=TargetMarket(**tm) if isinstance(tm, dict) else TargetMarket(),
            )

        p1 = data.get("phase_1", {})
        if p1:
            variables = []
            for v in p1.get("variables", []):
                candidates = [VariableCandidate(**c) for c in v.get("candidates", [])]
                variables.append(Variable(
                    name=v.get("name", ""),
                    role=v.get("role", ""),
                    initial_implementation=v.get("initial_implementation", ""),
                    initial_reason=v.get("initial_reason", ""),
                    candidates=candidates,
                ))
            mech = p1.get("mechanism", {})
            mechanism = Mechanism(
                statement=mech.get("statement", ""),
                prerequisites=mech.get("prerequisites", []),
                causal_chain=mech.get("causal_chain", []),
                falsification=mech.get("falsification", []),
                version=mech.get("version", 1),
            )
            predictions = []
            for p in p1.get("predictions", []):
                predictions.append(Prediction(
                    id=p.get("id", ""),
                    statement=p.get("statement", ""),
                    test_type=p.get("test_type", ""),
                    success_condition=p.get("success_condition", ""),
                    failure_learning=p.get("failure_learning", ""),
                    priority=p.get("priority", "medium"),
                    status=p.get("status", "pending"),
                    result=p.get("result", {}),
                ))
            h.phase_1 = Phase1(variables=variables, mechanism=mechanism, predictions=predictions)

        p2 = data.get("phase_2", {})
        if p2:
            history = []
            for entry in p2.get("refinement_history", []):
                history.append(RefinementEntry(
                    version=entry.get("version", 0),
                    failed_predictions=entry.get("failed_predictions", []),
                    interpretation=entry.get("interpretation", ""),
                    isolation_tests=entry.get("isolation_tests", []),
                    revision=entry.get("revision", ""),
                    new_predictions=entry.get("new_predictions", []),
                    timestamp=entry.get("timestamp", ""),
                ))
            h.phase_2 = Phase2(
                refinement_count=p2.get("refinement_count", 0),
                max_refinements=p2.get("max_refinements", 3),
                refinement_history=history,
            )

        p3 = data.get("phase_3", {})
        if p3:
            steps = {}
            for step_id, step_data in p3.get("steps", {}).items():
                if isinstance(step_data, dict):
                    steps[step_id] = ValidationStep(
                        status=step_data.get("status", "pending"),
                        result=step_data.get("result", {}),
                        interpretation=step_data.get("interpretation", ""),
                        timestamp=step_data.get("timestamp", ""),
                    )
            h.phase_3 = Phase3(steps=steps)

        p4 = data.get("phase_4", {})
        if p4:
            h.phase_4 = Phase4(
                report_path=p4.get("report_path", ""),
                summary_path=p4.get("summary_path", ""),
                generated_at=p4.get("generated_at", ""),
            )

        h.llm_cost = data.get("llm_cost", h.llm_cost)
        return h

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    @classmethod
    def load(cls, path: Path) -> Hypothesis:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)


def _to_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_dict(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, Enum):
        return obj.value
    return obj
