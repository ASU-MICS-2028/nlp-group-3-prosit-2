"""Shared helper: run one agent on the Claude Agent SDK, using only the tools we give it.

Every agent calls run_agent() the same way:

    usage = await run_agent(SYSTEM_PROMPT, prompt, tools)

`tools` maps a tool name to (description, input schema, the Python function that handles it).
The SDK runs the agent loop for us (Thought -> Action -> Observation): the model thinks, calls one
of our tools, reads what the tool answered, and repeats until it stops or hits a limit.
"""
import os

MODEL = os.getenv("LLM_MODEL", "claude-haiku-5-5")


async def run_agent(system: str, prompt: str, tools: dict, max_turns: int = 6, max_usd: float = 0.25) -> dict:
    """Run the agent until it stops. Returns {"tokens": ..., "cost_usd": ...}."""
    from claude_agent_sdk import (ClaudeAgentOptions, ClaudeSDKClient, ResultMessage,
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
    server = create_sdk_mcp_server(name="prosit", version="1.0.0", tools=sdk_tools)

    # 3. Lock the agent down: our tools only, no Bash, no files, no web, no local settings.
    options = ClaudeAgentOptions(
        model=MODEL,
        system_prompt=system,
        mcp_servers={"prosit": server},
        allowed_tools=[f"mcp__prosit__{name}" for name in tools],
        tools=[],                  # no built-in tools at all
        setting_sources=[],        # ignore local Claude Code settings and CLAUDE.md
        strict_mcp_config=True,    # ignore any other MCP servers on this machine
        max_turns=max_turns,       # stop rule: at most this many model steps
        max_budget_usd=max_usd,    # stop rule: at most this much money
    )

    # 4. Send the prompt and wait for the final result message.
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
