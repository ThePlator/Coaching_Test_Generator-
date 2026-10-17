"""LLM client interface, Ollama implementation and a fake for tests (LLD §4)."""

from __future__ import annotations

import base64
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

import httpx

from ctg.config import Settings

log = logging.getLogger("ctg.llm")


class LLMError(Exception):
    """Base class for model errors."""


class LLMUnavailable(LLMError):
    """Ollama server not reachable."""


class ModelMissing(LLMError):
    """Configured model is not pulled."""


class NoVisionModel(LLMError):
    """Photo/scan input but the model cannot read images."""


class LLMTimeout(LLMError):
    """A single call took longer than the timeout."""


class LLMBadOutput(LLMError):
    """The model returned something that is not valid JSON."""


@dataclass
class HealthStatus:
    server_up: bool
    model_present: bool
    vision: bool
    message: str

    @property
    def ok(self) -> bool:
        return self.server_up and self.model_present


class LLMClient(Protocol):
    def chat_json(self, system: str, user: str, schema: dict,
                  images: list[bytes] | None = None) -> dict: ...

    def chat_text(self, system: str, user: str,
                  images: list[bytes] | None = None) -> str: ...

    def health(self) -> HealthStatus: ...


class OllamaClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._http = httpx.Client(base_url=settings.ollama_host, timeout=settings.request_timeout_s)

    # -- public API -------------------------------------------------------

    def chat_json(self, system: str, user: str, schema: dict,
                  images: list[bytes] | None = None) -> dict:
        content = self._chat(system, user, images, fmt=schema)
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMBadOutput(f"invalid JSON from model ({len(content)} chars)") from e
        if not isinstance(data, dict):
            raise LLMBadOutput("model returned JSON that is not an object")
        return data

    def chat_text(self, system: str, user: str, images: list[bytes] | None = None) -> str:
        return self._chat(system, user, images, fmt=None)

    def health(self) -> HealthStatus:
        try:
            tags = self._http.get("/api/tags", timeout=5).json()
        except httpx.HTTPError:
            return HealthStatus(False, False, False,
                                "Gemma is not running. Open a terminal and run `ollama serve`.")
        names = {m.get("name") for m in tags.get("models", [])} | {m.get("model") for m in tags.get("models", [])}
        if self.s.model not in names and f"{self.s.model}:latest" not in names:
            return HealthStatus(True, False, False,
                                f"Model not installed. Run `ollama pull {self.s.model}` (one-time).")
        vision = False
        try:
            info = self._http.post("/api/show", json={"model": self.s.model}, timeout=10).json()
            vision = "vision" in (info.get("capabilities") or [])
        except httpx.HTTPError:
            pass
        msg = "Ready" if vision else "Ready (this model cannot read photos)"
        return HealthStatus(True, True, vision, msg)

    def warm_up(self) -> None:
        """Load the model into memory so the first real call is not cold."""
        try:
            self._http.post("/api/generate", json={"model": self.s.model, "keep_alive": self.s.keep_alive},
                            timeout=self.s.request_timeout_s)
        except httpx.HTTPError as e:
            log.info("warm-up failed: %s", type(e).__name__)

    # -- internals --------------------------------------------------------

    def _chat(self, system: str, user: str, images: list[bytes] | None, fmt: dict | None) -> str:
        model = self.s.model if images or not self.s.text_model else self.s.text_model
        user_msg: dict[str, Any] = {"role": "user", "content": user}
        if images:
            user_msg["images"] = [base64.b64encode(b).decode("ascii") for b in images]
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, user_msg],
            "stream": False,
            "keep_alive": self.s.keep_alive,
            "options": {
                "temperature": self.s.temperature,
                "num_ctx": self.s.num_ctx,
                "num_predict": self.s.num_predict,
                "top_p": 0.9,
            },
        }
        if fmt is not None:
            payload["format"] = fmt
        body = self._post("/api/chat", payload)
        log.info("chat model=%s prompt_tokens=%s gen_tokens=%s seconds=%.1f",
                 model, body.get("prompt_eval_count"), body.get("eval_count"),
                 body.get("total_duration", 0) / 1e9)
        return body.get("message", {}).get("content", "")

    def _post(self, path: str, payload: dict) -> dict:
        for attempt in (1, 2):  # one silent retry on transport errors
            try:
                r = self._http.post(path, json=payload)
            except httpx.TimeoutException as e:
                raise LLMTimeout(f"model call took longer than {self.s.request_timeout_s}s") from e
            except httpx.TransportError as e:
                if attempt == 2:
                    raise LLMUnavailable("cannot reach Ollama") from e
                continue
            if r.status_code == 404:
                raise ModelMissing(f"model {payload.get('model')} not found")
            if r.status_code >= 400:
                raise LLMBadOutput(f"Ollama error {r.status_code}: {r.text[:200]}")
            return r.json()
        raise LLMUnavailable("cannot reach Ollama")


Responder = Callable[[str, str, dict, "list[bytes] | None"], Any]


@dataclass
class FakeLLMClient:
    """Test double. Each call takes the next queued item (dict/str/Exception/callable);
    when the queue is empty it falls back to `responder`."""

    json_queue: deque = field(default_factory=deque)
    text_queue: deque = field(default_factory=deque)
    responder: Responder | None = None
    text_responder: Responder | None = None
    vision: bool = True
    calls: list[dict] = field(default_factory=list)

    def chat_json(self, system, user, schema, images=None) -> dict:
        self.calls.append({"kind": "json", "system": system, "user": user, "schema": schema})
        return self._next(self.json_queue, self.responder, system, user, schema, images)

    def chat_text(self, system, user, images=None) -> str:
        self.calls.append({"kind": "text", "system": system, "user": user, "images": images})
        return self._next(self.text_queue, self.text_responder, system, user, {}, images)

    def health(self) -> HealthStatus:
        return HealthStatus(True, True, self.vision, "Ready (fake)")

    @staticmethod
    def _next(queue, responder, system, user, schema, images):
        item = queue.popleft() if queue else responder
        if item is None:
            raise LLMBadOutput("FakeLLMClient has no response queued")
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(system, user, schema, images)
            if isinstance(item, Exception):
                raise item
        return item
