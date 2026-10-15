import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

import httpx


class LLMError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class ProviderConfig:
    provider_key: str
    base_url: str
    api_key: str | None
    model: str
    extra_headers: dict[str, str]
    timeout_s: int = 30


def _expand_extra_headers(extra: dict[str, str]) -> dict[str, str]:
    out = {}
    for k, v in extra.items():
        if "{{uuid}}" in v or "{uuid}" in v:
            v = v.replace("{{uuid}}", str(uuid.uuid4())).replace("{uuid}", str(uuid.uuid4()))
        out[k] = v
    return out


class LLMProvider:
    def __init__(self, config: ProviderConfig):
        self.config = config

    def _client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(self.config.timeout_s, connect=5.0)
        return httpx.AsyncClient(timeout=timeout)

    def _validate_opencode_session(self, headers: dict[str, str]) -> None:
        if self.config.provider_key == "opencode-go":
            if "x-opencode-session" not in {k.lower(): v for k, v in headers.items()}:
                raise LLMError("MissingSessionID", status_code=400)

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs: Any,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        headers.update(_expand_extra_headers(self.config.extra_headers))
        self._validate_opencode_session(headers)

        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        payload.update(kwargs)

        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        last_error: Exception | None = None
        for attempt in range(2):
            async with self._client() as client:
                try:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 400:
                        raise LLMError(
                            f"LLM gateway returned 400: {resp.text}", status_code=400
                        )
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data.get("choices", [{}])[0]
                    message = choice.get("message", {})
                    content = message.get("content")
                    if isinstance(content, str):
                        try:
                            parsed = json.loads(content)
                        except Exception:
                            parsed = content
                    else:
                        parsed = content
                    return {
                        "content": parsed,
                        "reasoning_content": message.get("reasoning_content"),
                        "raw": data,
                    }
                except LLMError:
                    raise
                except Exception as exc:
                    last_error = exc
                    if attempt == 0:
                        continue
        raise LLMError(f"LLM request failed: {last_error}", status_code=502)

    async def ping(self) -> bool:
        try:
            await self.chat(
                messages=[{"role": "user", "content": "Ping"}],
                max_tokens=5,
            )
            return True
        except Exception:
            return False
