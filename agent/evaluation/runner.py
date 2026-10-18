"""Unattended execution of Agent evaluation cases."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
from pathlib import Path
import queue
import re
import shutil
import threading
import time
import uuid
from typing import Callable, Protocol

import agent.platform.config as config
from agent.evaluation.approvals import (
    EvalApprovalDecision,
    decide_eval_approval,
)
from agent.evaluation.cases import EvalCase, load_cases, validate_cases
from agent.evaluation.judge import EvaluationJudge, LLMJudge
from agent.evaluation.scoring import (
    TrialObservation,
    score_case,
    trial_passed,
)
from agent.orchestration.approval_coordinator import approval_coordinator
from agent.platform.identity import system_admin_principal


@dataclass(frozen=True)
class RunConfig:
    cases_dir: Path
    fixtures_dir: Path
    run_root: Path
    batch_id: str = ""
    label: str = ""
    model_id: str = ""
    trials_per_case: int = 1
    categories: tuple[str, ...] = ()
    case_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    stop_on_failure: bool = False
    keep_workspaces: bool = False
    judge_enabled: bool = False
    judge_model_id: str = ""
    judge_threshold: float = 0.7


@dataclass
class BatchResult:
    batch_id: str
    started_at: float
    finished_at: float
    trials: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        completed = [
            item for item in self.trials
            if item.get("status") == "completed"
        ]
        passed = [item for item in completed if item.get("passed")]
        by_category: dict[str, dict] = {}
        for item in self.trials:
            category = str(item.get("category") or "unknown")
            entry = by_category.setdefault(category, {
                "trials": 0,
                "completed": 0,
                "passed": 0,
                "failed": 0,
                "cost_cny": 0.0,
                "judge_cost_cny": 0.0,
            })
            entry["trials"] += 1
            entry["cost_cny"] += float(item.get("cost_cny") or 0)
            entry["judge_cost_cny"] += float(
                item.get("judge_cost_cny") or 0
            )
            if item.get("status") == "completed":
                entry["completed"] += 1
                if item.get("passed"):
                    entry["passed"] += 1
                else:
                    entry["failed"] += 1
        agent_cost = sum(
            float(item.get("cost_cny") or 0)
            for item in self.trials
        )
        judge_cost = sum(
            float(item.get("judge_cost_cny") or 0)
            for item in self.trials
        )
        return {
            "batch_id": self.batch_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": int(
                max(0.0, self.finished_at - self.started_at) * 1000
            ),
            "trials": len(self.trials),
            "completed": len(completed),
            "passed": len(passed),
            "failed": len(completed) - len(passed),
            "pass_rate": len(passed) / len(completed) if completed else 0.0,
            "agent_cost_cny": agent_cost,
            "judge_cost_cny": judge_cost,
            "total_cost_cny": agent_cost + judge_cost,
            "by_category": by_category,
            "results": self.trials,
        }


class EvaluationStore(Protocol):
    def start_batch(self, config: RunConfig, *, total_cases: int, planned: int) -> None:
        ...

    def start_trial(
        self,
        *,
        case: EvalCase,
        trial_no: int,
        session_id: str,
    ) -> int | None:
        ...

    def finish_trial(
        self,
        trial_id: int | None,
        *,
        result: dict,
        scores: list[dict],
    ) -> None:
        ...

    def finish_batch(self, *, error: str = "") -> None:
        ...


class NullEvaluationStore:
    """Keep reports local when no evaluation database is selected."""

    def start_batch(self, config: RunConfig, *, total_cases: int, planned: int) -> None:
        return None

    def start_trial(
        self,
        *,
        case: EvalCase,
        trial_no: int,
        session_id: str,
    ) -> int | None:
        return None

    def finish_trial(
        self,
        trial_id: int | None,
        *,
        result: dict,
        scores: list[dict],
    ) -> None:
        return None

    def finish_batch(self, *, error: str = "") -> None:
        return None


class PostgresEvaluationStore:
    """Persist batches into the isolated evaluation database."""

    def __init__(self, batch_id: str, *, model_id: str = ""):
        from agent.persistence import database

        if not database.persistence_enabled():
            raise RuntimeError(
                "Evaluation storage requires DATABASE_URL"
            )
        database_name = config.DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0]
        if (
            config.DATABASE_URL.startswith("postgresql")
            and "eval" not in database_name.lower()
        ):
            raise RuntimeError(
                "Refusing to write evaluation rows to a non-evaluation "
                f"database: {database_name!r}"
            )
        self.batch_id = batch_id
        self.model_id = model_id

    def start_batch(
        self,
        config: RunConfig,
        *,
        total_cases: int,
        planned: int,
    ) -> None:
        from agent.persistence.repositories import eval as eval_repo

        eval_repo.create_batch(
            self.batch_id,
            suite="mixed" if len(config.categories) != 1 else config.categories[0],
            label=config.label,
            model_id=config.model_id or self.model_id,
            trials_per_case=config.trials_per_case,
            total_cases=total_cases,
            planned_trials=planned,
            config={
                "cases_dir": str(config.cases_dir),
                "fixtures_dir": str(config.fixtures_dir),
                "categories": list(config.categories),
                "case_ids": list(config.case_ids),
                "tags": list(config.tags),
            },
        )

    def start_trial(
        self,
        *,
        case: EvalCase,
        trial_no: int,
        session_id: str,
    ) -> int:
        from agent.persistence.repositories import eval as eval_repo

        return eval_repo.create_trial(
            batch_id=self.batch_id,
            case_id=case.id,
            trial_no=trial_no,
            category=case.category,
            severity=case.severity,
            topic=case.topic,
            session_id=session_id,
        )

    def finish_trial(
        self,
        trial_id: int | None,
        *,
        result: dict,
        scores: list[dict],
    ) -> None:
        if trial_id is None:
            return
        from agent.persistence.repositories import eval as eval_repo

        eval_repo.update_trial(
            trial_id,
            status=result["status"],
            run_id=result["run_id"],
            session_id=result["session_id"],
            final_answer=result["final_answer"],
            error=result["error"],
            tool_calls=len(result["tool_calls"]),
            input_tokens=result["input_tokens"],
            output_tokens=result["output_tokens"],
            cost_cny=result["cost_cny"],
            duration_ms=result["duration_ms"],
            approvals_requested=result["approvals_requested"],
            approvals_granted=result["approvals_granted"],
            trajectory=result["trajectory"],
        )
        eval_repo.add_tool_calls(
            trial_id,
            self.batch_id,
            result["case_id"],
            result["tool_calls"],
        )
        eval_repo.add_scores(
            trial_id,
            self.batch_id,
            result["case_id"],
            scores,
        )

    def finish_batch(self, *, error: str = "") -> None:
        from agent.persistence.repositories import eval as eval_repo

        status = "failed" if error else "completed"
        eval_repo.finish_batch(
            self.batch_id,
            status=status,
            error=error,
        )


def _safe_name(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return clean[:100] or "case"


def _within(root: Path, path: Path) -> bool:
    resolved_root = root.resolve(strict=False)
    resolved = path.resolve(strict=False)
    return resolved == resolved_root or resolved.is_relative_to(resolved_root)


@contextmanager
def _isolated_runtime(run_root: Path):
    """Keep fixture and backup files inside one disposable directory."""
    run_root.mkdir(parents=True, exist_ok=True)
    from agent.targets import tools as target_tools

    snapshots = {
        "target_roots": config.TARGET_BROWSE_ROOTS,
        "target_backups": target_tools.TARGET_BACKUP_ROOT,
    }
    try:
        config.TARGET_BROWSE_ROOTS = (run_root.resolve(),)
        target_tools.TARGET_BACKUP_ROOT = run_root / "target_backups"
        yield
    finally:
        config.TARGET_BROWSE_ROOTS = snapshots["target_roots"]
        target_tools.TARGET_BACKUP_ROOT = snapshots["target_backups"]


class EvalRunner:
    def __init__(
        self,
        config: RunConfig,
        *,
        store: EvaluationStore | None = None,
        agent_factory: Callable[..., object] | None = None,
        judge_factory: Callable[[], EvaluationJudge] | None = None,
    ):
        self.config = config
        self.store = store or NullEvaluationStore()
        self.agent_factory = agent_factory
        self.judge_factory = judge_factory
        self._judge: EvaluationJudge | None = None
        self.cases: list[EvalCase] = []

    def load(self) -> list[EvalCase]:
        cases, errors = load_cases(self.config.cases_dir)
        errors.extend(validate_cases(cases, self.config.fixtures_dir))
        if errors:
            raise ValueError("; ".join(errors))

        selected = cases
        if self.config.categories:
            allowed = set(self.config.categories)
            selected = [
                case for case in selected
                if case.category in allowed
            ]
        if self.config.case_ids:
            allowed_ids = set(self.config.case_ids)
            selected = [
                case for case in selected
                if case.id in allowed_ids
            ]
        if self.config.tags:
            allowed_tags = set(self.config.tags)
            selected = [
                case for case in selected
                if allowed_tags.intersection(case.tags)
            ]
        if not selected:
            raise ValueError("no evaluation cases selected")
        self.cases = selected
        return selected

    def run(self) -> dict:
        cases = self.cases or self.load()
        batch_id = self.config.batch_id or (
            f"eval_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        )
        effective = RunConfig(
            **{
                **self.config.__dict__,
                "batch_id": batch_id,
                "trials_per_case": max(1, int(self.config.trials_per_case)),
            }
        )
        planned = len(cases) * effective.trials_per_case
        self.store.start_batch(
            effective,
            total_cases=len(cases),
            planned=planned,
        )
        result = BatchResult(
            batch_id=batch_id,
            started_at=time.time(),
            finished_at=time.time(),
        )
        batch_error = ""
        try:
            if config.DATABASE_URL.startswith("sqlite"):
                from agent.persistence import database

                database.create_all()
            with _isolated_runtime(effective.run_root):
                for case in cases:
                    for trial_no in range(1, effective.trials_per_case + 1):
                        item = self._run_trial(
                            effective,
                            case,
                            trial_no,
                        )
                        result.trials.append(item)
                        if (
                            effective.stop_on_failure
                            and not item.get("passed")
                        ):
                            batch_error = (
                                f"stopped after failed case {case.id}"
                            )
                            break
                    if batch_error:
                        break
        except Exception as exc:
            batch_error = str(exc)
            raise
        finally:
            result.finished_at = time.time()
            try:
                self.store.finish_batch(error=batch_error)
            except Exception:
                if not batch_error:
                    raise
        report = result.to_dict()
        report["label"] = effective.label
        report["model_id"] = effective.model_id
        return report

    def _run_trial(
        self,
        config: RunConfig,
        case: EvalCase,
        trial_no: int,
    ) -> dict:
        session_id = (
            f"eval_{config.batch_id}_{_safe_name(case.id)}_"
            f"{trial_no}_{uuid.uuid4().hex[:6]}"
        )
        trial_id = self.store.start_trial(
            case=case,
            trial_no=trial_no,
            session_id=session_id,
        )
        workspace = (
            config.run_root
            / "workspaces"
            / _safe_name(case.id)
            / f"trial_{trial_no}"
        )
        target_dir = workspace / "target"
        target_id = ""
        observation = None
        try:
            if case.fixture:
                fixture_dir = config.fixtures_dir / case.fixture
                if not _within(config.run_root, workspace):
                    raise ValueError("evaluation workspace escapes run root")
                if workspace.exists():
                    shutil.rmtree(workspace)
                shutil.copytree(fixture_dir, target_dir)

                from agent.targets.store import TargetStore

                log_path = ""
                if (target_dir / "logs" / "app.log").is_file():
                    log_path = "logs/app.log"
                target = TargetStore().create({
                    "name": f"eval-{case.id}",
                    "root": str(target_dir),
                    "service": case.service,
                    "log_path": log_path,
                })
                target_id = target.id

            started = time.perf_counter()
            observation = self._execute(
                config,
                case,
                session_id=session_id,
                target_id=target_id,
                target_dir=target_dir,
            )
            observation.duration_ms = max(
                observation.duration_ms,
                int((time.perf_counter() - started) * 1000),
            )
            judge_result = None
            if case.judge_rubric and config.judge_enabled:
                judge_result = self._evaluate_with_judge(
                    config,
                    case,
                    observation,
                )
            scores = score_case(
                case,
                observation,
                judge_result=judge_result,
            )
            passed = trial_passed(scores)
            item = {
                "case_id": case.id,
                "category": case.category,
                "topic": case.topic,
                "severity": case.severity,
                "trial_no": trial_no,
                "status": observation.status,
                "passed": passed,
                "run_id": observation.run_id,
                "session_id": observation.session_id,
                "final_answer": observation.final_answer,
                "error": observation.error,
                "target_root": observation.target_root,
                "tool_calls": observation.tool_calls,
                "input_tokens": observation.input_tokens,
                "output_tokens": observation.output_tokens,
                "cost_cny": observation.cost_cny,
                "judge_cost_cny": float(
                    (judge_result or {})
                    .get("evidence", {})
                    .get("cost_cny") or 0
                ),
                "duration_ms": observation.duration_ms,
                "approvals_requested": observation.approvals_requested,
                "approvals_granted": observation.approvals_granted,
                "trajectory": observation.trajectory,
                "scores": scores,
                "worker_alive": observation.worker_alive,
            }
            if (
                case.fixture
                and not config.keep_workspaces
                and not observation.worker_alive
            ):
                item["target_root"] = ""
            self.store.finish_trial(
                trial_id,
                result=item,
                scores=scores,
            )
            return item
        finally:
            if case.fixture and not config.keep_workspaces:
                worker_alive = bool(
                    observation is not None
                    and observation.worker_alive
                )
                if not worker_alive:
                    if not _within(config.run_root, workspace):
                        raise ValueError(
                            "refusing to remove workspace outside run root"
                        )
                    from agent.targets.store import TargetStore

                    if target_id:
                        try:
                            TargetStore().delete(target_id)
                        except KeyError:
                            pass
                    shutil.rmtree(workspace, ignore_errors=True)

    def _evaluate_with_judge(
        self,
        config: RunConfig,
        case: EvalCase,
        observation: TrialObservation,
    ) -> dict:
        if self._judge is None:
            if self.judge_factory is not None:
                self._judge = self.judge_factory()
            else:
                self._judge = LLMJudge(
                    model_id=config.judge_model_id or config.model_id,
                    threshold=config.judge_threshold,
                )
        return self._judge.evaluate(case, observation).to_score()

    def _execute(
        self,
        config: RunConfig,
        case: EvalCase,
        *,
        session_id: str,
        target_id: str,
        target_dir: Path,
    ) -> TrialObservation:
        principal = system_admin_principal()
        factory = self.agent_factory
        try:
            if factory is None:
                from agent.core.comprehensive import ComprehensiveAgent

                factory = ComprehensiveAgent
            agent = factory(
                session_id=session_id,
                target_id=target_id,
                principal=principal,
                memory_scope=(
                    f"eval:{config.batch_id}:{case.id}:{session_id[-6:]}"
                ),
                max_turns=case.max_turns,
            )
            if config.model_id:
                agent.model = config.model_id
                agent.recovery.current_model = config.model_id
        except Exception as exc:
            return TrialObservation(
                status="failed",
                error=f"agent initialization failed: {exc}",
                session_id=session_id,
                target_root=str(target_dir) if case.fixture else "",
            )

        cancel_event = threading.Event()
        messages: queue.Queue = queue.Queue()

        def worker():
            run_id = ""
            try:
                for event in agent.run_stream(case.prompt, cancel_event):
                    run_id = str(getattr(agent, "current_run_id", "") or run_id)
                    messages.put(("event", event, run_id))
                    if event.get("type") == "pending_action":
                        action = event.get("pending_action") or {}
                        if cancel_event.is_set():
                            decision = EvalApprovalDecision(
                                False,
                                "run cancelled before approval",
                            )
                        else:
                            decision = decide_eval_approval(
                                case,
                                action,
                                target_root=target_dir if case.fixture else "",
                            )
                        resolved = approval_coordinator.resolve(
                            str(action.get("id") or ""),
                            approved=decision.approved,
                            actor="evaluation-runner",
                            reason=decision.reason,
                        )
                        messages.put((
                            "approval",
                            {
                                "action_id": action.get("id", ""),
                                "approved": decision.approved,
                                "reason": decision.reason,
                            },
                            run_id,
                        ))
                        if not resolved:
                            cancel_event.set()
                            messages.put((
                                "exception",
                                RuntimeError(
                                    "approval waiter was not registered"
                                ),
                                run_id,
                            ))
            except Exception as exc:
                messages.put(("exception", exc, run_id))
            finally:
                messages.put(("end", None, run_id))

        thread = threading.Thread(
            target=worker,
            name=f"eval-{case.id}-{session_id[-6:]}",
            daemon=True,
        )
        thread.start()

        observation = TrialObservation(
            status="failed",
            session_id=session_id,
            target_root=str(target_dir) if case.fixture else "",
        )
        open_calls: list[int] = []
        deadline = time.monotonic() + case.timeout_seconds
        timed_out = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                cancel_event.set()
                observation.status = "timeout"
                observation.error = (
                    f"trial exceeded {case.timeout_seconds}s timeout"
                )
                break
            try:
                kind, payload, run_id = messages.get(timeout=remaining)
            except queue.Empty:
                timed_out = True
                cancel_event.set()
                observation.status = "timeout"
                observation.error = (
                    f"trial exceeded {case.timeout_seconds}s timeout"
                )
                break

            if run_id:
                observation.run_id = run_id
            if kind == "approval":
                observation.approvals_granted += int(bool(payload["approved"]))
                observation.trajectory.append({
                    "type": "eval_approval",
                    **payload,
                })
                continue
            if kind == "exception":
                observation.status = "failed"
                observation.error = str(payload)
                observation.trajectory.append({
                    "type": "eval_exception",
                    "message": str(payload),
                })
                continue
            if kind == "end":
                break

            event = payload
            observation.trajectory.append(event)
            event_type = str(event.get("type") or "")
            if event_type == "tool_use":
                observation.tool_calls.append({
                    "step": len(observation.tool_calls) + 1,
                    "tool": str(event.get("tool") or ""),
                    "arguments": dict(event.get("input") or {}),
                    "output": "",
                    "ok": True,
                    "duration_ms": 0,
                })
                open_calls.append(len(observation.tool_calls) - 1)
            elif event_type == "tool_result":
                if open_calls:
                    index = open_calls.pop(0)
                    call = observation.tool_calls[index]
                    call["output"] = str(event.get("output") or "")
                    call["duration_ms"] = int(event.get("duration_ms") or 0)
                    call["ok"] = not call["output"].startswith((
                        "Error:",
                        "Policy denied:",
                        "Approval rejected or cancelled:",
                    ))
            elif event_type == "pending_action":
                observation.approvals_requested += 1
            elif event_type == "done":
                observation.status = "completed"
                observation.final_answer = str(event.get("text") or "")
                usage = event.get("usage") or {}
                observation.input_tokens = int(usage.get("input") or 0)
                observation.output_tokens = int(usage.get("output") or 0)
                observation.cost_cny = float(usage.get("est_cost_cny") or 0)
            elif event_type == "cancelled":
                observation.status = "canceled"
                observation.final_answer = str(event.get("text") or "")
                observation.error = "run was cancelled"
            elif event_type == "error":
                observation.status = "failed"
                observation.error = str(event.get("message") or "")

        if timed_out or thread.is_alive():
            thread.join(timeout=2)
        observation.worker_alive = thread.is_alive()
        return observation


def write_report(report: dict, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return destination


__all__ = [
    "BatchResult",
    "EvalRunner",
    "EvaluationStore",
    "NullEvaluationStore",
    "PostgresEvaluationStore",
    "RunConfig",
    "write_report",
]
