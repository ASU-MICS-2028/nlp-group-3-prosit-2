"""LLM interface. Agents take any callable (system, messages) -> str.

get_llm() picks the provider from LLM_PROVIDER (gemini | claude | claude-code, default gemini).
FakeLLM is for offline unit tests.
"""
import json
import os
import subprocess
import tempfile
from typing import Protocol


class LLM(Protocol):
    tokens: int

    def __call__(self, system: str, messages: list[dict]) -> str: ...


def load_env(path: str = ".env") -> None:
    """Read KEY=value lines from .env into os.environ (existing vars win)."""
    if os.path.exists(path):
        for line in open(path):
            k, sep, v = line.strip().partition("=")
            if sep and not k.startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))


class ClaudeLLM:
    def __init__(self, model: str = None, max_tokens: int = 4096):
        import anthropic
        load_env()
        self.client = anthropic.Anthropic()
        self.model = model or os.getenv("LLM_MODEL", "claude-sonnet-5-5")
        self.max_tokens = max_tokens
        self.tokens = 0

    def __call__(self, system: str, messages: list[dict]) -> str:
        resp = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system, messages=messages,
        )
        self.tokens += resp.usage.input_tokens + resp.usage.output_tokens
        return "".join(b.text for b in resp.content if b.type == "text")


class GeminiLLM:
    def __init__(self, model: str = None, max_tokens: int = 8192):
        from google import genai
        from google.genai import types
        load_env()
        # short retry on 5xx, then fall back to the next model (quota is per model); 2 min cap per request
        retry = types.HttpRetryOptions(attempts=3, initial_delay=2, max_delay=10, http_status_codes=[500, 502, 503, 504])
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                                   http_options=types.HttpOptions(retry_options=retry, timeout=120_000))
        self.models = [model or os.getenv("LLM_MODEL", "gemini-3.8-flash")] + [
            m.strip() for m in os.getenv("LLM_FALLBACKS", "gemini-3.7-flash,gemini-3.5-flash").split(",") if m.strip()
        ]
        self.model = self.models[0]   # last model that answered
        self.max_tokens = max_tokens
        self.tokens = 0

    def __call__(self, system: str, messages: list[dict]) -> str:
        from google.genai import errors, types
        contents = [
            types.Content(role="model" if m["role"] == "assistant" else "user",
                          parts=[types.Part(text=m["content"])])
            for m in messages
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self.max_tokens,
            response_mime_type="application/json",  # both agents reply in JSON only
        )
        for i, model in enumerate(self.models):
            try:
                resp = self.client.models.generate_content(model=model, contents=contents, config=config)
                self.model = model
                break
            except (errors.ServerError, errors.ClientError) as e:
                # overloaded (5xx) or out of quota (429): try the next model
                if (isinstance(e, errors.ClientError) and e.code != 429) or i == len(self.models) - 1:
                    raise
        self.tokens += (resp.usage_metadata.total_token_count or 0) if resp.usage_metadata else 0
        return resp.text or ""


class ClaudeCodeLLM:
    """Claude through the local `claude` CLI, billed to the user's Claude subscription (no API key).

    Flags strip plugins, MCP servers, settings and tools so each call is ~1k tokens, not ~57k.
    """

    def __init__(self, model: str = None):
        load_env()
        self.model = model or os.getenv("LLM_MODEL", "sonnet")
        self.tokens = 0

    def __call__(self, system: str, messages: list[dict]) -> str:
        if len(messages) == 1:
            prompt = messages[0]["content"]
        else:  # the CLI takes one prompt, so pass the chat as a transcript
            turns = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
            prompt = f"Conversation so far:\n\n{turns}\n\nWrite the ASSISTANT's next reply to the last USER message."
        cmd = ["claude", "-p", "--system-prompt", system, "--model", self.model,
               "--output-format", "json", "--no-session-persistence", "--tools", "",
               "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands"]
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              timeout=300, cwd=tempfile.gettempdir())
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"claude CLI failed: {(proc.stderr or proc.stdout)[:300]}")
        if proc.returncode or data.get("is_error"):
            raise RuntimeError(f"claude CLI error: {str(data.get('result'))[:300]}")
        u = data.get("usage", {})
        self.tokens += sum(u.get(k, 0) for k in ("input_tokens", "output_tokens",
                                                 "cache_creation_input_tokens", "cache_read_input_tokens"))
        return data["result"]


def get_llm() -> "LLM":
    load_env()
    provider = os.getenv("LLM_PROVIDER", "gemini")
    return {"gemini": GeminiLLM, "claude": ClaudeLLM, "claude-code": ClaudeCodeLLM}[provider]()


class FakeLLM:
    """Returns scripted replies in order. Records every call for assertions."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[tuple[str, list[dict]]] = []
        self.tokens = 0

    def __call__(self, system: str, messages: list[dict]) -> str:
        self.calls.append((system, messages))
        return self.replies.pop(0)


def extract_json(text: str) -> dict:
    """Parse the first complete JSON object in an LLM reply.

    Tolerates ```json fences, prose around it, and extra objects after it (models
    sometimes send two steps at once; we take the first).
    """
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in reply: {text[:200]!r}")
    obj, _ = json.JSONDecoder().raw_decode(text, start)
    return obj
