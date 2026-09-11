"""Pydantic API request contract tests."""

import pytest
from pydantic import ValidationError

from api.schemas import ChatRequest, CronCreateRequest, TaskCreateRequest


def test_chat_request_rejects_empty_message():
    with pytest.raises(ValidationError):
        ChatRequest(message="")


def test_task_request_rejects_unknown_priority():
    with pytest.raises(ValidationError):
        TaskCreateRequest(subject="task", priority="urgent")


def test_cron_request_defaults_are_explicit():
    request = CronCreateRequest(cron="0 9 * * *", prompt="inspect")

    assert request.recurring is True
    assert request.enabled is True
    assert request.name == ""
    assert request.description == ""
