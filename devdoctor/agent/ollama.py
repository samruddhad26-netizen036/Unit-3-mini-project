"""Minimal Ollama client for local LLM inference.

Handles connection, requests, and basic error handling.
No external dependencies beyond stdlib.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class OllamaError(Exception):
    """Raised when Ollama communication fails."""

    message: str
    status_code: int | None = None


DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = os.environ.get("DEVDOCTOR_MODEL", "qwen2.5-coder:7b")


@dataclass
class OllamaClient:
    """Simple Ollama HTTP client for chat completions."""

    base_url: str = DEFAULT_OLLAMA_URL
    model: str = DEFAULT_MODEL
    timeout_s: float = 120.0

    def _request(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.base_url.rstrip('/')}{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OllamaError(f"Ollama HTTP {exc.code}: {body}", exc.code)
        except urllib.error.URLError as exc:
            raise OllamaError(f"Cannot connect to Ollama at {self.base_url}: {exc}")
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Invalid JSON from Ollama: {exc}")

    def is_available(self) -> bool:
        """Check if Ollama server is reachable."""
        try:
            with urllib.request.urlopen(
                f"{self.base_url.rstrip('/')}/api/tags", timeout=5.0
            ) as resp:
                return resp.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def list_models(self) -> list[str]:
        """Return available model names."""
        resp = self._request("/api/tags", {})
        return [m["name"] for m in resp.get("models", [])]

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Send a chat completion request with optional tool definitions."""
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        return self._request("/api/chat", payload)

    def generate(self, prompt: str, system: str | None = None) -> str:
        """Simple generate endpoint (for non-chat models)."""
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        resp = self._request("/api/generate", payload)
        return resp.get("response", "")