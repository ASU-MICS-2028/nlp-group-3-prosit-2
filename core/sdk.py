"""Shared helper: run one agent on the Claude Agent SDK, using only the tools we give it.

Every agent calls run_agent() the same way:

    usage = await run_agent(SYSTEM_PROMPT, prompt, tools)

`tools` maps a tool name to (description, input schema, the Python function that handles it).
The SDK runs the agent loop for us (Thought -> Action -> Observation): the model thinks, calls one
of our tools, reads what the tool answered, and repeats until it stops or hits a limit.

An agent that writes code also gets the SDK's file tools (Read, Write, Edit), locked to its project
folder by a PreToolUse hook: see allowed() below.
"""
import os
from pathlib import Path

MODEL = os.getenv("LLM_MODEL", "claude-haiku-5-5")
FILE_TOOLS = ["Read", "Write", "Edit"]
WRITABLE = ("app", "tests")   # the only folders an agent may write in, inside its project


def allowed(tool: str, path: str, workspace: str, writable: tuple = WRITABLE) -> bool:
    """Security rule for file tools: read only inside the project, write only in the writable folders
    (app/ and tests/ by default; the Tester gets tests/ only)."""
    ws = Path(workspace).resolve()
    target = (ws / path).resolve()   # an absolute path stays absolute; ".." and symlinks are resolved
    if tool == "Read":
        return target == ws or ws in target.parents
    return any(target.is_relative_to(ws / folder) and target != ws / folder for folder in writable)


def deny_reason(tool: str, tool_input: dict, workspace: str, writable: tuple = WRITABLE,
                edit_in_place: bool = False) -> str:
    """Why a file tool call is refused, or "" if it is fine."""
    path = tool_input.get("file_path", "")
    if not allowed(tool, path, workspace, writable):
        return (f"Not allowed: {path}. Read inside the project; write only in "
                + " or ".join(f"{folder}/" for folder in writable) + ".")
    if edit_in_place and tool == "Write" and (Path(workspace) / path).is_file() and tool_input.get("content", "").strip():
        return (f"{path} already exists. Use Edit to change only the part that needs changing "
                "(Write is for new files, or empty content to remove a file).")
    return ""


async def run_agent(system: str, prompt: str, tools: dict, max_turns: int = 6, max_usd: float = 0.25,
                    workspace: str | None = None, writable: tuple = WRITABLE, edit_in_place: bool = False) -> dict:
    """Run the agent until it stops. Returns {"tokens": ..., "cost_usd": ...}.
    With a workspace, the agent may also Read, Write and Edit files there (see allowed()).
    `writable` narrows the folders it may write in, e.g. ("tests",) for the Tester.
    `edit_in_place` (changes to an existing project): Write may create new files or empty old ones,
    but an existing file is changed with Edit, so only the part that needs changing is replaced."""
    from claude_agent_sdk import (ClaudeAgentOptions, ClaudeSDKClient, HookMatcher, ResultMessage,
                                  create_sdk_mcp_server, tool)

    # 1. Turn each of our Python functions into an SDK tool.
    def make_tool(name, description, schema, fn):
        @tool(name, description, schema)
        async def handler(args: dict) -> dict:
            answer = await fn(args)                                  # our code runs here
            return {"content": [{"type": "text", "text": answer}]}  # the model reads this answer
        return handler

    sdk_tools = [make_tool(name, d, s, fn) for name, (d, s, fn) in tools.items()]

    # 2. Serve the tools as an in-process MCP server called "prosit".
    #    The model sees them as mcp__prosit__<name>.
    servers = {"prosit": create_sdk_mcp_server(name="prosit", version="1.0.0", tools=sdk_tools)} if tools else {}
    allowed_tools = [f"mcp__prosit__{name}" for name in tools]

    # 3. File tools (only when there is a workspace), guarded by a hook that runs before every file tool call.
    builtin, hooks = [], {}
    if workspace:
        async def guard(input_data, tool_use_id, context):
            reason = deny_reason(input_data["tool_name"], input_data["tool_input"], workspace, writable, edit_in_place)
            if not reason:
                return {}   # no objection
            return {"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}

        builtin = FILE_TOOLS
        allowed_tools += FILE_TOOLS
        hooks = {"PreToolUse": [HookMatcher(matcher="|".join(FILE_TOOLS), hooks=[guard])]}

    # 4. Lock the agent down: our tools only (plus guarded file tools), no Bash, no web, no local settings.
    options = ClaudeAgentOptions(
        model=MODEL,
        system_prompt=system,
        mcp_servers=servers,
        allowed_tools=allowed_tools,
        tools=builtin,             # no built-in tools at all, or only Read/Write/Edit
        cwd=workspace,             # file paths are relative to the project folder
        hooks=hooks,
        setting_sources=[],        # ignore local Claude Code settings and CLAUDE.md
        strict_mcp_config=True,    # ignore any other MCP servers on this machine
        max_turns=max_turns,       # stop rule: at most this many model steps
        max_budget_usd=max_usd,    # stop rule: at most this much money
    )

    # 5. Send the prompt and wait for the final result message.
    usage = {"tokens": 0, "cost_usd": 0.0}
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            if isinstance(msg, ResultMessage):
                # Hitting max_turns or the budget is a normal stop; anything else is a real error.
                if msg.is_error and not msg.subtype.startswith("error_max"):
                    raise RuntimeError(msg.result or msg.subtype)
                u = msg.usage or {}
                usage["tokens"] = sum(u.get(k) or 0 for k in ("input_tokens", "output_tokens",
                                      "cache_read_input_tokens", "cache_creation_input_tokens"))
                usage["cost_usd"] = msg.total_cost_usd or 0.0
    return usage
