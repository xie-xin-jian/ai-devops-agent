from agent.platform.config import WORKDIR
from agent.platform.identity import Principal, system_admin_principal
from agent.tools import FILE_TOOL_HANDLERS, FILE_TOOL_SCHEMAS
from agent.tools.executor import ToolExecutor
from agent.tools.policy import ToolPolicyContext
from agent.tools.registry import ToolRegistry

SUB_SYSTEM = (
    f"You are a coding subagent at {WORKDIR}. "
    "Complete the task, then return a concise final summary. "
    "Only use the provided sandbox file tools. "
    "Do not execute host shell commands. Do not spawn more agents."
)

SUB_TOOLS = FILE_TOOL_SCHEMAS
SUBAGENT_ALLOWED_TOOLS = frozenset({
    "read_file",
    "write_file",
    "edit_file",
    "glob",
})

def extract_text(content) -> str:
    if not isinstance(content, list):
        return str(content)
    return "\n".join(
        getattr(block, "text", "")
        for block in content
        if getattr(block, "type", None) == "text").strip()


def has_tool_use(content) -> bool:
    return any(getattr(block, "type", None) == "tool_use"
               for block in content)


def spawn_subagent(
    client,
    model: str,
    description: str,
    *,
    sandbox_manager=None,
    run_id: str = "",
    principal: Principal | None = None,
) -> str:
    registry = ToolRegistry()
    registry.register_many(FILE_TOOL_SCHEMAS, FILE_TOOL_HANDLERS)
    principal = principal or system_admin_principal()
    executor = ToolExecutor(
        registry,
        sandbox_manager=sandbox_manager,
        sandbox_source=str(WORKDIR),
        principal=principal,
        tool_context=ToolPolicyContext(
            permissions=frozenset({"*"}),
            allowed_tools=SUBAGENT_ALLOWED_TOOLS,
            write_enabled=True,
            execute_enabled=False,
        ),
    )
    messages = [{"role": "user", "content": description}]
    for _ in range(30):
        response = client.messages.create(
            model=model, system=SUB_SYSTEM, messages=messages,
            tools=SUB_TOOLS, max_tokens=8000)
        messages.append({"role": "assistant", "content": response.content})
        if not has_tool_use(response.content):
            break
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                output = executor.execute(
                    block.name,
                    block.input,
                    run_id=run_id,
                    registry=registry,
                    source="subagent",
                ).output
            except Exception as exc:
                output = f"Error: {exc}"
            results.append({"type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(output)})
        messages.append({"role": "user", "content": results})
    for msg in reversed(messages):
        if msg["role"] == "assistant":
            text = extract_text(msg["content"])
            if text:
                return text
    return "Subagent finished without a text summary."
