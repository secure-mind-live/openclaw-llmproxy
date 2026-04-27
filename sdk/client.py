"""OpenClaw LLM Proxy Python SDK client."""

import json
from dataclasses import dataclass
from typing import Generator

import httpx


@dataclass
class ChatResponse:
    content: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    finish_reason: str
    trace_id: str | None
    raw: dict


class OpenClawClient:
    """Client for the OpenClaw LLM Proxy.

    Args:
        base_url: Proxy base URL (e.g., "http://localhost:8005")
        api_key: Proxy API key (team key in multi-tenant mode)
        timeout: Request timeout in seconds
    """

    def __init__(self, base_url: str = "http://localhost:8005",
                 api_key: str = "", timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def chat(self, model: str, message: str,
             system: str | None = None,
             messages: list[dict] | None = None,
             temperature: float = 0,
             max_tokens: int | None = None) -> ChatResponse:
        """Send a chat completion request.

        Args:
            model: Model name (e.g., "gpt-4", "claude-3-opus", "llama3.2:1b")
            message: User message (shorthand for single-turn)
            system: Optional system message
            messages: Full messages list (overrides message/system)
            temperature: Sampling temperature
            max_tokens: Max response tokens
        """
        if messages is None:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": message})

        body = {"model": model, "messages": messages, "temperature": temperature}
        if max_tokens:
            body["max_tokens"] = max_tokens

        resp = httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json=body,
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})

        return ChatResponse(
            content=choice.get("message", {}).get("content", ""),
            model=data.get("model", model),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            finish_reason=choice.get("finish_reason", ""),
            trace_id=resp.headers.get("x-request-id"),
            raw=data,
        )

    def stream(self, model: str, message: str,
               system: str | None = None,
               messages: list[dict] | None = None,
               temperature: float = 0) -> Generator[str, None, None]:
        """Stream a chat completion, yielding text chunks.

        Args:
            model: Model name
            message: User message
            system: Optional system message
            messages: Full messages list
            temperature: Sampling temperature
        """
        if messages is None:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": message})

        body = {"model": model, "messages": messages, "stream": True, "temperature": temperature}

        with httpx.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            json=body,
            headers=self._headers(),
            timeout=self.timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    return
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        yield text
                except json.JSONDecodeError:
                    continue

    def health(self) -> dict:
        """Check proxy health."""
        resp = httpx.get(f"{self.base_url}/health", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def spend(self) -> dict:
        """Get spend summary."""
        resp = httpx.get(
            f"{self.base_url}/spend",
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def logs(self, backend: str | None = None, model: str | None = None,
             limit: int = 50) -> dict:
        """Query request logs."""
        params = {"limit": limit}
        if backend:
            params["backend"] = backend
        if model:
            params["model"] = model
        resp = httpx.get(
            f"{self.base_url}/logs",
            params=params,
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def as_openai(self):
        """Return an OpenAI SDK client pointed at this proxy.

        Usage:
            client = OpenClawClient(base_url="http://localhost:8005", api_key="key")
            openai = client.as_openai()
            resp = openai.chat.completions.create(model="gpt-4", messages=[...])
        """
        try:
            from openai import OpenAI
            return OpenAI(
                base_url=f"{self.base_url}/v1",
                api_key=self.api_key,
            )
        except ImportError:
            raise ImportError("pip install openai to use as_openai()")
