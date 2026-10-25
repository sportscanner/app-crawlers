"""Minimal client for OpenAI-compatible Chat Completions APIs.

Used with OpenRouter (https://openrouter.ai/docs) or OpenCode
(https://opencode.ai/v2/docs/console/api/inference/): both take `POST
{base}/chat/completions` with `Authorization: Bearer <key>`. Plain httpx keeps
the dependency surface small: one blocking call shape (A2A) and one streamed
one (the website's agent mode).
"""

import json
from typing import Any, AsyncIterator, Optional

import httpx


class LLMError(RuntimeError):
    """Raised when the LLM provider can't produce a completion.

    `public_message` is safe to show to the calling agent; the full detail is
    only logged.
    """

    def __init__(self, public_message: str, detail: str = ""):
        super().__init__(detail or public_message)
        self.public_message = public_message


_STATUS_MESSAGES = {
    401: "Sportscanner Agent's LLM credentials are invalid.",
    402: "Sportscanner Agent's LLM account has run out of credit.",
    403: "Sportscanner Agent's LLM key is not allowed to use this model.",
    429: "Sportscanner Agent is rate limited. Try again shortly.",
}


# reasoning_details parts arrive in fragments; these fields are concatenated per index.
_STREAMED_TEXT_FIELDS = {"text", "summary", "data", "signature"}


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str],
        base_url: str,
        model: str,
        provider: str = "LLM",
        headers: Optional[dict[str, str]] = None,
        timeout: float = 90.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.model = model
        self.provider = provider
        self._headers = headers or {}
        self._timeout = timeout
        # Injectable so tests can stub the provider without network access.
        self._transport = transport

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        max_tokens: int = 1500,
        tool_choice: str = "auto",
    ) -> dict[str, Any]:
        """Return the assistant message dict from the first choice."""
        if not self._api_key:
            raise LLMError(f"Sportscanner Agent is not configured (missing {self.provider} API key).")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            try:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={**self._headers, "Authorization": f"Bearer {self._api_key}"},
                )
            except httpx.HTTPError as exc:
                raise LLMError("Sportscanner Agent couldn't reach its LLM provider.", str(exc)) from exc

        if response.status_code != 200:
            raise LLMError(
                _STATUS_MESSAGES.get(response.status_code, "Sportscanner Agent's LLM provider returned an error."),
                f"{self.provider} {response.status_code}: {response.text[:500]}",
            )
        try:
            return response.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMError("Sportscanner Agent got an unreadable LLM response.", response.text[:500]) from exc

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        max_tokens: int = 1500,
        tool_choice: str = "auto",
    ) -> AsyncIterator[tuple[str, Any]]:
        """Stream a completion: yields ("delta", text) as answer text arrives,
        then ("message", assistant_message) once, with tool-call fragments
        reassembled into the same shape `chat()` returns."""
        if not self._api_key:
            raise LLMError(f"Sportscanner Agent is not configured (missing {self.provider} API key).")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        content: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        # Reasoning models (DeepSeek via OpenRouter) stream their reasoning too. It
        # has to go back with the tool-call turn, as it does unstreamed, or the
        # model loses its thread and repeats searches instead of answering.
        reasoning: list[str] = []
        details: dict[int, dict[str, Any]] = {}
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={**self._headers, "Authorization": f"Bearer {self._api_key}"},
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode(errors="replace")
                        raise LLMError(
                            _STATUS_MESSAGES.get(
                                response.status_code, "Sportscanner Agent's LLM provider returned an error."
                            ),
                            f"{self.provider} {response.status_code}: {body[:500]}",
                        )
                    async for line in response.aiter_lines():
                        # SSE: "data: {...}" chunks; ": comment" keep-alives; "data: [DONE]" at the end.
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except ValueError:
                            continue
                        if chunk.get("error"):
                            raise LLMError(
                                "Sportscanner Agent's LLM provider returned an error.",
                                f"{self.provider} stream error: {str(chunk['error'])[:500]}",
                            )
                        for choice in chunk.get("choices") or []:
                            delta = choice.get("delta") or {}
                            if delta.get("content"):
                                content.append(delta["content"])
                                yield "delta", delta["content"]
                            if delta.get("reasoning"):
                                reasoning.append(delta["reasoning"])
                            for part in delta.get("reasoning_details") or []:
                                merged = details.setdefault(part.get("index", len(details)), {})
                                for key, value in part.items():
                                    if key in _STREAMED_TEXT_FIELDS and isinstance(value, str):
                                        merged[key] = merged.get(key, "") + value
                                    else:
                                        merged[key] = value
                            for part in delta.get("tool_calls") or []:
                                call = calls.setdefault(
                                    part.get("index", len(calls)),
                                    {"id": None, "type": "function", "function": {"name": "", "arguments": ""}},
                                )
                                call["id"] = part.get("id") or call["id"]
                                fn = part.get("function") or {}
                                call["function"]["name"] += fn.get("name") or ""
                                call["function"]["arguments"] += fn.get("arguments") or ""
            except httpx.HTTPError as exc:
                raise LLMError("Sportscanner Agent couldn't reach its LLM provider.", str(exc)) from exc

        message: dict[str, Any] = {"role": "assistant", "content": "".join(content) or None}
        if reasoning:
            message["reasoning"] = "".join(reasoning)
        if details:
            message["reasoning_details"] = [details[i] for i in sorted(details)]
        if calls:
            message["tool_calls"] = [calls[i] for i in sorted(calls)]
        yield "message", message


def client_from_settings() -> LLMClient:
    """Build the client for the provider selected by A2A_LLM_PROVIDER."""
    from sportscanner.variables import settings

    if settings.A2A_LLM_PROVIDER == "opencode":
        return LLMClient(
            api_key=settings.OPENCODE_API_KEY,
            base_url=settings.OPENCODE_BASE_URL,
            model=settings.A2A_MODEL,
            provider="OpenCode",
        )
    return LLMClient(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        model=settings.A2A_MODEL,
        provider="OpenRouter",
        # Optional OpenRouter app attribution headers.
        headers={"HTTP-Referer": "https://www.sportscanner.co.uk", "X-Title": "Sportscanner Agent"},
    )
