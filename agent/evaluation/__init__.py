"""Evaluation primitives and the offline Agent trial runner."""

from agent.evaluation.baseline import compare_reports, load_report
from agent.evaluation.cases import EvalCase, load_cases, validate_cases
from agent.evaluation.judge import JudgeVerdict, LLMJudge
from agent.evaluation.runner import EvalRunner, RunConfig
from agent.evaluation.scoring import TrialObservation, score_case

__all__ = [
    "EvalCase",
    "EvalRunner",
    "JudgeVerdict",
    "LLMJudge",
    "compare_reports",
    "load_report",
    "RunConfig",
    "TrialObservation",
    "load_cases",
    "score_case",
    "validate_cases",
]
