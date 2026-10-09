"""Recovery API tests for interrupted runs and safe resume."""

import threading

from agent.platform import config
from agent.sessions.state_store import RecoveryStore


def _store(tmp_path):
    return RecoveryStore(
        sessions_dir=tmp_path / ".sessions",
        runs_dir=tmp_path / ".runs",
    )


def test_recovery_api_lists_and_rejects_unsafe_resume(
    tmp_path,
    monkeypatch,
):
    from fastapi.testclient import TestClient
    from api.main import app

    monkeypatch.setattr(config, "SESSIONS_DIR", tmp_path / ".sessions")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / ".runs")
    store = _store(tmp_path)
    store.save_run(
        "run-unsafe",
        session_id="session-1",
        owner_id="api-user",
        source="chat",
        status="interrupted",
        phase="interrupted",
        user_message="restart nginx",
        messages=[{"role": "user", "content": "restart nginx"}],
        safe_to_resume=False,
        interruption_reason="crashed while tool was running",
    )

    client = TestClient(app)
    listed = client.get("/api/recovery/runs")
    detail = client.get("/api/recovery/runs/run-unsafe")
    resume = client.post("/api/recovery/runs/run-unsafe/resume/stream")

    assert listed.status_code == 200
    assert listed.json()["runs"][0]["run_id"] == "run-unsafe"
    assert detail.status_code == 200
    assert detail.json()["safe_to_resume"] is False
    assert "crashed while tool" in detail.json()["interruption_reason"]
    assert resume.status_code == 409


def test_recovery_api_streams_from_safe_point(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import api.main
    from api.main import app

    monkeypatch.setattr(config, "SESSIONS_DIR", tmp_path / ".sessions")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / ".runs")
    store = _store(tmp_path)
    store.save_run(
        "run-safe",
        session_id="session-1",
        owner_id="api-user",
        source="chat",
        status="interrupted",
        phase="interrupted",
        user_message="check disk",
        messages=[{"role": "user", "content": "check disk"}],
        safe_to_resume=True,
        interruption_reason="process restarted",
    )

    class FakeAgent:
        def resume_stream(self, run_id, messages, cancel_event):
            assert run_id == "run-safe"
            assert messages[0]["content"] == "check disk"
            yield {"type": "status", "message": "resuming", "turn": 1}
            yield {"type": "done", "text": "disk ok", "total_turns": 1}

    fake_session = {
        "agent": FakeAgent(),
        "cancel_event": threading.Event(),
        "run_lock": threading.Lock(),
    }
    monkeypatch.setattr(
        api.main,
        "get_or_create_session",
        lambda session_id, principal: ("session-1", fake_session),
    )

    client = TestClient(app)
    response = client.post("/api/recovery/runs/run-safe/resume/stream")

    assert response.status_code == 200
    assert "resuming" in response.text
    assert "disk ok" in response.text
