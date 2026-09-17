"""Tool catalog consistency tests."""

from agent import comprehensive


def test_tool_catalog_contains_all_registered_tools():
    names = {
        tool["name"]
        for tool in comprehensive.ComprehensiveAgent.get_tool_catalog()
    }

    assert {
        "add_memory",
        "search_memory",
        "update_memory",
        "archive_memory",
        "delete_memory",
        "restore_memory",
        "list_cron_logs",
        "list_background_tasks",
        "schedule_cron",
        "spawn_subagent",
    }.issubset(names)
