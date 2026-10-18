"""Deterministic scoring for one evaluation trial."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path

from agent.evaluation.cases import EvalCase, rule_name


@dataclass
class TrialObservation:
    status: str
    final_answer: str = ""
    error: str = ""
    run_id: str = ""
    session_id: str = ""
    target_root: str = ""
    trajectory: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    approvals_requested: int = 0
    approvals_granted: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_cny: float = 0.0
    duration_ms: int = 0
    worker_alive: bool = False


def _safe_target_path(target_root: str, relative: object) -> Path:
    root = Path(target_root).expanduser().resolve(strict=False)
    candidate = root / str(relative or "")
    resolved = candidate.resolve(strict=False)
    if resolved != root and not resolved.is_relative_to(root):
        raise ValueError(f"evaluation path escapes target: {relative}")
    return resolved


def _result(
    rule: str,
    passed: bool,
    detail: str,
    *,
    evidence: dict | None = None,
    skipped: bool = False,
    error: bool = False,
) -> dict:
    status = "error" if error else "skip" if skipped else "pass" if passed else "fail"
    return {
        "rule": rule,
        "status": status,
        "score": 0.0 if error or skipped else 1.0 if passed else 0.0,
        "detail": detail,
        "evidence": evidence or {},
    }


def _tool_names(observation: TrialObservation) -> set[str]:
    return {
        str(item.get("tool") or "")
        for item in observation.tool_calls
        if item.get("tool")
    }


def _score_rule(
    case: EvalCase,
    rule,
    observation: TrialObservation,
) -> dict:
    name = rule_name(rule)
    answer = observation.final_answer or ""
    names = _tool_names(observation)

    if name == "run_completed":
        return _result(
            name,
            observation.status == "completed",
            f"trial status={observation.status}",
        )

    if name == "tool_called":
        spec = rule.get(name) if isinstance(rule, dict) else {}
        any_of = {str(item) for item in (spec or {}).get("any_of") or []}
        all_of = {str(item) for item in (spec or {}).get("all_of") or []}
        if any_of:
            passed = bool(any_of & names)
            expected = sorted(any_of)
        else:
            passed = bool(all_of) and all_of.issubset(names)
            expected = sorted(all_of)
        return _result(
            name,
            passed,
            f"called={sorted(names)} expected={expected}",
            evidence={"called": sorted(names), "expected": expected},
        )

    if name == "tool_not_called":
        forbidden = {
            str(item)
            for item in (
                rule.get(name)
                if isinstance(rule, dict)
                else rule
            ) or []
        }
        called = sorted(forbidden & names)
        return _result(
            name,
            not called,
            f"forbidden calls={called}",
            evidence={"forbidden": sorted(forbidden), "called": called},
        )

    if name == "max_tool_calls":
        limit = int(
            rule.get(name)
            if isinstance(rule, dict)
            else rule
        )
        count = len(observation.tool_calls)
        return _result(
            name,
            count <= limit,
            f"tool_calls={count} limit={limit}",
            evidence={"count": count, "limit": limit},
        )

    if name == "answer_matches":
        pattern = str(
            rule.get(name)
            if isinstance(rule, dict)
            else rule
        )
        try:
            passed = bool(re.search(pattern, answer, re.IGNORECASE | re.DOTALL))
        except re.error as exc:
            return _result(name, False, f"invalid regex: {exc}", error=True)
        return _result(
            name,
            passed,
            f"regex={pattern!r}",
            evidence={"pattern": pattern, "answer": answer[:2000]},
        )

    if name == "answer_contains_any":
        keywords = [
            str(item)
            for item in (
                rule.get(name)
                if isinstance(rule, dict)
                else rule
            ) or []
        ]
        lowered = answer.casefold()
        passed = any(item.casefold() in lowered for item in keywords)
        return _result(
            name,
            passed,
            f"matched={passed}",
            evidence={"keywords": keywords, "answer": answer[:2000]},
        )

    if name == "answer_not_contains":
        keywords = [
            str(item)
            for item in (
                rule.get(name)
                if isinstance(rule, dict)
                else rule
            ) or []
        ]
        lowered = answer.casefold()
        leaked = [item for item in keywords if item.casefold() in lowered]
        return _result(
            name,
            not leaked,
            f"leaked={leaked}",
            evidence={"keywords": keywords, "leaked": leaked},
        )

    if name == "answer_max_chars":
        limit = int(
            rule.get(name)
            if isinstance(rule, dict)
            else rule
        )
        return _result(
            name,
            len(answer) <= limit,
            f"chars={len(answer)} limit={limit}",
            evidence={"chars": len(answer), "limit": limit},
        )

    if name in {
        "file_exists",
        "file_absent",
        "file_content_matches",
    }:
        if not observation.target_root:
            return _result(
                name,
                False,
                "case has no target workspace",
                error=True,
            )
        try:
            spec = rule.get(name) if isinstance(rule, dict) else rule
            if name == "file_content_matches":
                if not isinstance(spec, dict):
                    return _result(name, False, "rule requires a mapping", error=True)
                path = _safe_target_path(
                    observation.target_root,
                    spec.get("path"),
                )
                pattern = str(spec.get("pattern") or "")
                exists = path.is_file()
                content = (
                    path.read_text(encoding="utf-8", errors="replace")
                    if exists
                    else ""
                )
                matched = bool(
                    re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                ) if pattern and exists else False
                return _result(
                    name,
                    matched,
                    f"path={path} exists={exists} matched={matched}",
                    evidence={"path": str(path), "pattern": pattern},
                )
            path = _safe_target_path(observation.target_root, spec)
            exists = path.exists()
            passed = exists if name == "file_exists" else not exists
            return _result(
                name,
                passed,
                f"path={path} exists={exists}",
                evidence={"path": str(path), "exists": exists},
            )
        except (OSError, ValueError) as exc:
            return _result(name, False, str(exc), error=True)

    if name == "approval_requested":
        expected = (
            bool(rule.get(name))
            if isinstance(rule, dict)
            else True
        )
        actual = observation.approvals_requested > 0
        return _result(
            name,
            actual == expected,
            f"requested={actual} expected={expected}",
            evidence={
                "requested": observation.approvals_requested,
                "granted": observation.approvals_granted,
            },
        )

    if name == "no_failed_tool":
        failed = []
        for item in observation.tool_calls:
            output = str(item.get("output") or "")
            if output.startswith((
                "Error:",
                "Policy denied:",
                "Approval rejected or cancelled:",
            )):
                failed.append(item)
        return _result(
            name,
            not failed,
            f"failed_tools={len(failed)}",
            evidence={
                "failed": [
                    {
                        "tool": item.get("tool"),
                        "output": str(item.get("output") or "")[:1000],
                    }
                    for item in failed
                ],
            },
        )

    if name == "max_cost_cny":
        limit = float(
            rule.get(name)
            if isinstance(rule, dict)
            else rule
        )
        return _result(
            name,
            float(observation.cost_cny) <= limit,
            f"cost_cny={observation.cost_cny:.6f} limit={limit}",
            evidence={"cost_cny": observation.cost_cny, "limit": limit},
        )

    if name == "max_duration_seconds":
        limit = float(
            rule.get(name)
            if isinstance(rule, dict)
            else rule
        )
        duration_seconds = observation.duration_ms / 1000
        return _result(
            name,
            duration_seconds <= limit,
            f"duration_seconds={duration_seconds:.3f} limit={limit}",
            evidence={"duration_seconds": duration_seconds, "limit": limit},
        )

    return _result(
        name or "unknown",
        False,
        f"unknown rule: {rule!r}",
        error=True,
    )


def score_case(
    case: EvalCase,
    observation: TrialObservation,
    *,
    judge_result: dict | None = None,
) -> list[dict]:
    scores = [
        _score_rule(case, rule, observation)
        for rule in case.expect
    ]
    if case.judge_rubric:
        scores.append(
            judge_result
            if judge_result is not None
            else _result(
                "judge_rubric",
                False,
                "LLM judge is not enabled for this run",
                evidence={"rubric": case.judge_rubric},
                skipped=True,
            )
        )
    return scores


def trial_passed(scores: list[dict]) -> bool:
    return bool(scores) and not any(
        item.get("status") in {"fail", "error"}
        for item in scores
    )


__all__ = ["TrialObservation", "score_case", "trial_passed"]
