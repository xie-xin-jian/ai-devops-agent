"""The plain-language persistence report shown to the operator."""

from __future__ import annotations

from scripts.persistence_health import report


def _payload(**overrides) -> dict:
    persistence = {
        "backend": "dual",
        "mirror": {
            "enabled": True,
            "totals": {"calls": 12, "failures": 0, "skipped": 0},
        },
        "read_mode": "json",
        "shadow_checks": 0,
        "shadow_mismatches": 0,
    }
    persistence.update(overrides)
    return {"persistence": persistence}


def test_healthy_dual_mode_reports_ok():
    lines, ok = report(_payload())
    text = "\n".join(lines)

    assert ok is True
    assert "已开启" in text
    assert "0 次" in text
    assert "一切正常" in text


def test_mirror_failures_are_flagged():
    payload = _payload()
    payload["persistence"]["mirror"]["totals"]["failures"] = 3

    lines, ok = report(payload)

    assert ok is False
    assert "有 3 次没写进 PostgreSQL" in "\n".join(lines)


def test_switched_reads_are_described():
    payload = _payload(
        read_mode="postgres",
        postgres_reads=["targets", "tasks"],
        shadow_checks=20,
        shadow_mismatches=0,
    )

    lines, ok = report(payload)
    text = "\n".join(lines)

    assert ok is True
    assert "targets、tasks" in text
    assert "两边完全一致" in text


def test_shadow_mismatch_is_flagged():
    payload = _payload(
        read_mode="postgres",
        postgres_reads=["targets"],
        shadow_checks=20,
        shadow_mismatches=2,
    )

    lines, ok = report(payload)

    assert ok is False
    assert "需要处理" in "\n".join(lines)
