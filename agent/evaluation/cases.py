"""Load and validate evaluation cases from YAML."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


REQUIRED_FIELDS = {
    "id",
    "category",
    "prompt",
    "timeout_seconds",
    "max_turns",
    "approvals",
    "expect",
}
KNOWN_RULES = {
    "run_completed",
    "tool_called",
    "tool_not_called",
    "max_tool_calls",
    "answer_matches",
    "answer_contains_any",
    "answer_not_contains",
    "answer_max_chars",
    "file_exists",
    "file_absent",
    "file_content_matches",
    "approval_requested",
    "no_failed_tool",
    "max_cost_cny",
    "max_duration_seconds",
}
APPROVAL_POLICIES = {
    "auto_readonly",
    "auto_approve",
    "deny_all",
    "allow_list",
}
CATEGORIES = {"core", "boundary", "abnormal", "faq"}


def rule_name(rule: Any) -> str:
    if isinstance(rule, str):
        return rule
    if isinstance(rule, dict) and len(rule) == 1:
        return str(next(iter(rule)))
    return ""


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    prompt: str
    timeout_seconds: int
    max_turns: int
    approvals: str
    expect: tuple[Any, ...]
    topic: str = ""
    severity: str = "medium"
    fixture: str = ""
    service: str = ""
    allow_commands: tuple[str, ...] = ()
    judge_rubric: str = ""
    tags: tuple[str, ...] = ()
    notes: str = ""
    source: str = ""
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_mapping(
        cls,
        data: dict,
        *,
        source: str = "",
    ) -> "EvalCase":
        return cls(
            id=str(data.get("id") or "").strip(),
            category=str(data.get("category") or "").strip(),
            topic=str(data.get("topic") or "").strip(),
            severity=str(data.get("severity") or "medium").strip(),
            prompt=str(data.get("prompt") or ""),
            fixture=str(data.get("fixture") or "").strip(),
            service=str(data.get("service") or "").strip(),
            timeout_seconds=max(1, int(data.get("timeout_seconds") or 120)),
            max_turns=max(1, int(data.get("max_turns") or 8)),
            approvals=str(data.get("approvals") or "").strip(),
            allow_commands=tuple(
                str(item)
                for item in data.get("allow_commands") or []
                if str(item).strip()
            ),
            judge_rubric=str(data.get("judge_rubric") or ""),
            expect=tuple(data.get("expect") or []),
            tags=tuple(str(item) for item in data.get("tags") or []),
            notes=str(data.get("notes") or ""),
            source=source,
            raw=dict(data),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "topic": self.topic,
            "severity": self.severity,
            "prompt": self.prompt,
            "fixture": self.fixture,
            "service": self.service,
            "timeout_seconds": self.timeout_seconds,
            "max_turns": self.max_turns,
            "approvals": self.approvals,
            "allow_commands": list(self.allow_commands),
            "judge_rubric": self.judge_rubric,
            "expect": list(self.expect),
            "tags": list(self.tags),
            "notes": self.notes,
            "source": self.source,
        }


def load_cases(cases_dir: str | Path) -> tuple[list[EvalCase], list[str]]:
    root = Path(cases_dir)
    cases: list[EvalCase] = []
    errors: list[str] = []
    paths = sorted(root.glob("*.yaml"))
    if not paths:
        return [], [f"no case files under {root}"]

    for path in paths:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{path.name}: invalid YAML: {exc}")
            continue
        if not isinstance(data, list):
            errors.append(f"{path.name}: top level must be a list")
            continue
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                errors.append(f"{path.name}[{index}]: case must be a mapping")
                continue
            try:
                cases.append(EvalCase.from_mapping(
                    item,
                    source=f"{path.name}[{index}]",
                ))
            except (TypeError, ValueError) as exc:
                errors.append(f"{path.name}[{index}]: {exc}")
    return cases, errors


def validate_cases(
    cases: list[EvalCase],
    fixtures_dir: str | Path,
) -> list[str]:
    errors: list[str] = []
    fixtures_root = Path(fixtures_dir)
    for duplicate, count in Counter(case.id for case in cases).items():
        if duplicate and count > 1:
            errors.append(f"duplicate id: {duplicate}")

    for case in cases:
        where = case.source or case.id or "?"
        if case.category not in CATEGORIES:
            errors.append(f"{where}: unknown category {case.category!r}")
        if case.approvals not in APPROVAL_POLICIES:
            errors.append(
                f"{where}: unknown approvals policy {case.approvals!r}"
            )
        if case.approvals == "allow_list" and not case.allow_commands:
            errors.append(f"{where}: allow_list requires allow_commands")
        if case.severity not in {"low", "medium", "high"}:
            errors.append(f"{where}: unknown severity {case.severity!r}")

        fixture_dir = (
            fixtures_root / case.fixture
            if case.fixture
            else None
        )
        if fixture_dir is not None and not fixture_dir.is_dir():
            errors.append(f"{where}: fixture not found: {case.fixture}")

        for rule in case.expect:
            name = rule_name(rule)
            if name not in KNOWN_RULES:
                errors.append(f"{where}: unknown rule {rule!r}")
                continue
            if name == "file_absent" and fixture_dir is not None:
                relative = (
                    rule.get(name)
                    if isinstance(rule, dict)
                    else rule
                )
                if not (fixture_dir / str(relative)).exists():
                    errors.append(
                        f"{where}: file_absent target is missing from fixture: "
                        f"{relative}"
                    )
    return errors


__all__ = [
    "APPROVAL_POLICIES",
    "CATEGORIES",
    "EvalCase",
    "KNOWN_RULES",
    "load_cases",
    "rule_name",
    "validate_cases",
]
