"""The plain-language persistence report shown to the operator."""

from __future__ import annotations

from scripts.persistence_health import report


def _payload(**overrides) -> dict:
    persistence = {
        "database_url_configured": True,
        "database_reachable": True,
        "database_status": "ok",
        "dialect": "postgresql",
    }
    persistence.update(overrides)
    return {"persistence": persistence}


def test_healthy_database_reports_ok():
    lines, ok = report(_payload())
    text = "\n".join(lines)

    assert ok is True
    assert "postgresql" in text
    assert "连接正常" in text
    assert "数据库正常" in text


def test_unreachable_database_is_flagged():
    payload = _payload(
        database_reachable=False,
        database_status="connection refused",
    )

    lines, ok = report(payload)

    assert ok is False
    assert "connection refused" in "\n".join(lines)
