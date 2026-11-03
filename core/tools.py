"""Tool format shared by all agents. Same shape as an MCP tool (name, description, inputSchema)."""
from dataclasses import dataclass
from typing import Callable


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict          # JSON Schema for the args object
    fn: Callable[..., str]      # called with the args as keyword arguments, returns the observation

    def to_mcp(self) -> dict:
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema}


def describe(tools: list[Tool]) -> str:
    """Render tools for a text ReAct prompt."""
    import json
    return "\n".join(f"- {t.name}: {t.description}\n  args schema: {json.dumps(t.input_schema)}" for t in tools)
