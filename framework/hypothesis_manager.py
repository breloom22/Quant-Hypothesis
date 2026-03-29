"""가설 문서 CRUD + 상태 관리"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .schema import Hypothesis, Status


STRATEGIES_DIR = Path(__file__).resolve().parents[1] / "strategies"


def strategy_dir(name: str) -> Path:
    return STRATEGIES_DIR / name


def hypothesis_path(name: str) -> Path:
    return strategy_dir(name) / "hypothesis.yaml"


def create_hypothesis(name: str) -> Hypothesis:
    """새 가설 생성 (Phase 0)"""
    path = hypothesis_path(name)
    if path.exists():
        raise FileExistsError(f"전략 '{name}'이 이미 존재합니다: {path}")

    h = Hypothesis(
        strategy_name=name,
        created_at=datetime.now().isoformat(timespec="seconds"),
        status=Status.PHASE_0_INTAKE.value,
    )
    h.save(path)
    return h


def load_hypothesis(name: str) -> Hypothesis:
    path = hypothesis_path(name)
    if not path.exists():
        raise FileNotFoundError(f"전략 '{name}'을 찾을 수 없습니다: {path}")
    return Hypothesis.load(path)


def save_hypothesis(h: Hypothesis) -> None:
    path = hypothesis_path(h.strategy_name)
    h.save(path)


def update_status(name: str, status: Status) -> Hypothesis:
    h = load_hypothesis(name)
    h.status = status.value
    save_hypothesis(h)
    return h


def list_strategies() -> list[dict]:
    """모든 전략과 현재 상태 반환"""
    results = []
    if not STRATEGIES_DIR.exists():
        return results
    for d in sorted(STRATEGIES_DIR.iterdir()):
        hp = d / "hypothesis.yaml"
        if hp.exists():
            h = Hypothesis.load(hp)
            results.append({
                "name": h.strategy_name,
                "status": h.status,
                "created_at": h.created_at,
            })
    return results


def load_prompt(prompt_name: str) -> str:
    """시스템 프롬프트 파일 로드"""
    prompt_path = Path(__file__).resolve().parent / "llm" / "prompts" / prompt_name
    if not prompt_path.exists():
        raise FileNotFoundError(f"프롬프트 파일을 찾을 수 없습니다: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")
