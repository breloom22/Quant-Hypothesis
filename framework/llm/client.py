"""LLM API 클라이언트 — Claude Sonnet 4.6 + DeepSeek V3.2 하이브리드"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
import openai
import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


def load_config(config_path: str = "config.yaml") -> dict:
    path = Path(config_path)
    if not path.exists():
        path = Path(__file__).resolve().parents[2] / "config.yaml"
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    # 환경 변수 치환
    def _resolve(val: Any) -> Any:
        if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
            env_key = val[2:-1]
            return os.environ.get(env_key, "")
        if isinstance(val, dict):
            return {k: _resolve(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_resolve(v) for v in val]
        return val

    return _resolve(raw)


class LLMClient:
    """Claude Sonnet 4.6 + DeepSeek V3.2 하이브리드 클라이언트"""

    def __init__(self, config: dict | None = None):
        if config is None:
            config = load_config()

        llm_cfg = config["llm"]

        # Anthropic (Sonnet)
        self._sonnet_model = llm_cfg["anthropic"]["model"]
        self._sonnet_max_tokens = llm_cfg["anthropic"]["max_tokens"]
        self._sonnet = anthropic.Anthropic(api_key=llm_cfg["anthropic"]["api_key"])

        # DeepSeek (OpenAI-compatible)
        self._deepseek_model = llm_cfg["deepseek"]["model"]
        self._deepseek_max_tokens = llm_cfg["deepseek"]["max_tokens"]
        self._deepseek = openai.OpenAI(
            api_key=llm_cfg["deepseek"]["api_key"],
            base_url=llm_cfg["deepseek"]["base_url"],
        )

        # 비용 추적
        self.usage = {
            "sonnet_input_tokens": 0,
            "sonnet_output_tokens": 0,
            "deepseek_input_tokens": 0,
            "deepseek_output_tokens": 0,
        }

    # ── 공개 메서드 ──────────────────────────────────────────

    def reason(self, system_prompt: str, user_message: str, context: str | None = None) -> LLMResponse:
        """추론 작업 -> Sonnet"""
        return self._call_sonnet(system_prompt, user_message, context)

    def interpret(self, system_prompt: str, user_message: str, context: str | None = None) -> LLMResponse:
        """결과 해석 (예상 밖 포함) -> Sonnet"""
        return self._call_sonnet(system_prompt, user_message, context)

    def generate_code(self, system_prompt: str, user_message: str, context: str | None = None) -> LLMResponse:
        """코드 생성 -> DeepSeek"""
        return self._call_deepseek(system_prompt, user_message, context)

    def analyze(self, system_prompt: str, user_message: str, context: str | None = None) -> LLMResponse:
        """정형 분석 -> DeepSeek"""
        return self._call_deepseek(system_prompt, user_message, context)

    def call(self, task_type: str, system_prompt: str, user_message: str, context: str | None = None) -> LLMResponse:
        """router 기반 자동 라우팅"""
        from .router import get_model_for_task
        model = get_model_for_task(task_type)
        if model == "sonnet":
            return self._call_sonnet(system_prompt, user_message, context)
        return self._call_deepseek(system_prompt, user_message, context)

    def get_cost_summary(self) -> dict:
        """현재 세션의 비용 요약"""
        sonnet_cost = (
            self.usage["sonnet_input_tokens"] / 1_000_000 * 3.0
            + self.usage["sonnet_output_tokens"] / 1_000_000 * 15.0
        )
        deepseek_cost = (
            self.usage["deepseek_input_tokens"] / 1_000_000 * 0.28
            + self.usage["deepseek_output_tokens"] / 1_000_000 * 0.42
        )
        return {
            "sonnet": {"tokens": self.usage["sonnet_input_tokens"] + self.usage["sonnet_output_tokens"],
                       "cost_usd": round(sonnet_cost, 4)},
            "deepseek": {"tokens": self.usage["deepseek_input_tokens"] + self.usage["deepseek_output_tokens"],
                         "cost_usd": round(deepseek_cost, 4)},
            "total_cost_usd": round(sonnet_cost + deepseek_cost, 4),
        }

    # ── 내부 메서드 ──────────────────────────────────────────

    def _build_messages(self, user_message: str, context: str | None) -> list[dict]:
        messages = []
        if context:
            messages.append({"role": "user", "content": context})
            messages.append({"role": "assistant", "content": "이전 컨텍스트를 확인했습니다. 이어서 진행하겠습니다."})
        messages.append({"role": "user", "content": user_message})
        return messages

    def _call_sonnet(self, system_prompt: str, user_message: str, context: str | None) -> LLMResponse:
        messages = self._build_messages(user_message, context)
        t0 = time.perf_counter_ns()

        response = self._sonnet.messages.create(
            model=self._sonnet_model,
            max_tokens=self._sonnet_max_tokens,
            system=system_prompt,
            messages=messages,
        )

        latency = (time.perf_counter_ns() - t0) // 1_000_000
        inp = response.usage.input_tokens
        out = response.usage.output_tokens
        self.usage["sonnet_input_tokens"] += inp
        self.usage["sonnet_output_tokens"] += out

        return LLMResponse(
            content=response.content[0].text,
            model=self._sonnet_model,
            input_tokens=inp,
            output_tokens=out,
            latency_ms=latency,
        )

    def _call_deepseek(self, system_prompt: str, user_message: str, context: str | None) -> LLMResponse:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self._build_messages(user_message, context))
        t0 = time.perf_counter_ns()

        response = self._deepseek.chat.completions.create(
            model=self._deepseek_model,
            max_tokens=self._deepseek_max_tokens,
            messages=messages,
        )

        latency = (time.perf_counter_ns() - t0) // 1_000_000
        inp = response.usage.prompt_tokens
        out = response.usage.completion_tokens
        self.usage["deepseek_input_tokens"] += inp
        self.usage["deepseek_output_tokens"] += out

        return LLMResponse(
            content=response.choices[0].message.content,
            model=self._deepseek_model,
            input_tokens=inp,
            output_tokens=out,
            latency_ms=latency,
        )
