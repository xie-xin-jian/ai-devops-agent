"""Cron and background tool registration."""

from __future__ import annotations


from agent.orchestration.background import list_background_tasks
from agent.orchestration.cron import cancel_job, schedule_job


class AutomationToolsMixin:
    def _add_cron_tools(self):
        tools = [
            {
                "name": "schedule_cron",
                "description": "Schedule a recurring prompt using cron syntax (5 fields: min hour dom month dow). Cron jobs will auto-execute in background at the scheduled time (no need to wait for user message).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "cron": {"type": "string"},
                        "prompt": {"type": "string"},
                        "recurring": {"type": "boolean", "default": True},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "enabled": {"type": "boolean", "default": True},
                    },
                    "required": ["cron", "prompt"],
                },
            },
            {
                "name": "list_crons",
                "description": "List all scheduled cron jobs with their last run status.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "cancel_cron",
                "description": "Cancel a scheduled cron job by ID.",
                "input_schema": {
                    "type": "object",
                    "properties": {"job_id": {"type": "string"}},
                    "required": ["job_id"],
                },
            },
            {
                "name": "list_cron_logs",
                "description": "List cron job execution history (recent N runs). Each entry has fired_at, finished_at, success, output, error.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Optional. Filter by specific job ID.",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 10,
                            "description": "Max number of logs to return, default 10.",
                        },
                    },
                    "required": [],
                },
            },
        ]
        from agent.orchestration.cron import (
            scheduled_jobs,
            _last_fired,
            list_cron_run_logs,
        )

        def _schedule(
            cron,
            prompt,
            recurring=True,
            name="",
            description="",
            enabled=True,
        ):
            job, message = schedule_job(
                cron,
                prompt,
                recurring,
                name=name,
                description=description,
                enabled=enabled,
            )
            if job is None:
                return message
            label = job.name or job.id
            return f"Scheduled {job.id} ({label}, {job.cron})"

        handlers = {
            "schedule_cron": _schedule,
            "list_crons": lambda: "\n".join(
                f"  {j.id}: {j.name or '(unnamed)'} | {j.cron}"
                f" {'recurring' if j.recurring else 'once'}"
                f" | last_run={_last_fired.get(j.id).strftime('%H:%M:%S') if _last_fired.get(j.id) else 'never'}"
                f" | prompt={j.prompt[:50]}"
                for j in scheduled_jobs.values()
            )
            or "No scheduled jobs.",
            "cancel_cron": lambda job_id: cancel_job(job_id),
            "list_cron_logs": lambda job_id=None, limit=10: (
                (
                    lambda logs: "\n".join(
                        f"  [{log.get('fired_at', '?')}] job={log.get('job_id','?')[:12]} "
                        f"success={log.get('success')} "
                        f"{(log.get('output') or '')[:80]}"
                        f"{' error=' + str(log.get('error'))[:60] if log.get('error') else ''}"
                        for log in logs
                    )
                    or "No cron run logs yet."
                )(list_cron_run_logs(job_id=job_id, limit=limit))
            ),
        }
        self.tool_registry.register_many(tools, handlers)

    def _add_background_tools(self):
        schema = {
            "name": "list_background_tasks",
            "description": (
                "List all background tasks with their current status (running/completed). "
                "By default output is summarized; set full=true for complete captured output. "
                "Does NOT consume/modify them — safe to call repeatedly. "
                "Use this to check whether a background task finished and read its result. "
                "Prefer this over collect_background_results when you need to re-check a task."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "full": {
                        "type": "boolean",
                        "default": False,
                        "description": "Return complete captured output instead of a head/tail summary.",
                    },
                },
                "required": [],
            },
        }
        self.tool_registry.register(
            schema,
            lambda full=False: list_background_tasks(full=full),
        )
