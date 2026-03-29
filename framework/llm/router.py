"""작업 유형 -> 모델 라우팅"""

ROUTING: dict[str, str] = {
    # Phase 1
    "variable_decomposition": "sonnet",
    "mechanism_hypothesis": "sonnet",
    "prediction_generation": "sonnet",
    "signal_code_generation": "deepseek",
    "test_code_generation": "deepseek",

    # Phase 2
    "failure_interpretation": "sonnet",
    "isolation_test_design": "sonnet",
    "mechanism_revision": "sonnet",
    "new_prediction_from_revision": "sonnet",
    "isolation_code_generation": "deepseek",

    # Phase 3
    "routine_result_check": "deepseek",
    "unexpected_result_interp": "sonnet",
    "filter_design": "sonnet",
    "filter_code_generation": "deepseek",
    "failure_analysis_interp": "sonnet",
    "cross_validation_design": "sonnet",

    # Phase 4
    "report_generation": "deepseek",
    "report_insight_addition": "sonnet",
}


def get_model_for_task(task_type: str) -> str:
    """작업 유형에 대한 모델 반환. 알 수 없는 작업은 deepseek(비용 절약)."""
    return ROUTING.get(task_type, "deepseek")
