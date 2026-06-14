"""
patchguard/providers.py — Multi-Provider LLM Abstraction Layer

Supports three providers in priority order:
  1. Gemini (Google Generative AI) — Primary
  2. OpenRouter — Fallback
  3. Ollama — Optional Offline Fallback

Provider selection is automatic based on available credentials.
Users never enter API keys — server-side environment variables are used.
"""

import json
import os
import re
import time
import urllib.request
import urllib.error
from dataclasses import dataclass


@dataclass
class ProviderStatus:
    """Tracks which provider is active and its health."""
    name: str
    model: str
    available: bool
    latency_ms: int = 0
    error: str = ""


class ModelProvider:
    """
    Unified interface for LLM inference across Gemini, OpenRouter, and Ollama.
    
    Automatic fallback chain:
        Gemini → OpenRouter → Ollama
    
    Environment Variables:
        GOOGLE_API_KEY       : Google Gemini API key (primary)
        OPENROUTER_API_KEY   : OpenRouter API key (fallback)
        OLLAMA_HOST          : Ollama server URL (default: http://localhost:11434)
        GEMINI_MODEL         : Gemini model name (default: gemini-2.5-flash)
        OPENROUTER_MODEL     : OpenRouter model (default: qwen/qwen3-32b)
        OLLAMA_MODEL         : Ollama model (default: qwen2.5:7b)
    """

    # Provider constants
    GEMINI = "gemini"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"

    def __init__(self):
        self._google_api_key = os.environ.get("GOOGLE_API_KEY", "")
        self._openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self._ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

        self._gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        self._openrouter_model = os.environ.get("OPENROUTER_MODEL", "qwen/qwen3-32b")
        self._ollama_model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

        self._active_provider: str | None = None
        self._active_model: str = ""
        self._detect_provider()

    def _detect_provider(self):
        """Detect the best available provider based on credentials."""
        if self._google_api_key and self._google_api_key != "dummy":
            self._active_provider = self.GEMINI
            self._active_model = self._gemini_model
        elif self._openrouter_api_key and self._openrouter_api_key != "dummy":
            self._active_provider = self.OPENROUTER
            self._active_model = self._openrouter_model
        else:
            # Try Ollama as last resort
            self._active_provider = self.OLLAMA
            self._active_model = self._ollama_model

    @property
    def active_provider(self) -> str:
        """Return the name of the currently active provider."""
        return self._active_provider or "none"

    @property
    def active_model(self) -> str:
        """Return the model identifier of the currently active provider."""
        return self._active_model

    @property
    def display_name(self) -> str:
        """Human-readable label for the active provider and model."""
        labels = {
            self.GEMINI: f"Gemini {self._gemini_model}",
            self.OPENROUTER: f"OpenRouter {self._openrouter_model}",
            self.OLLAMA: f"Ollama {self._ollama_model}",
        }
        return labels.get(self._active_provider, "No Provider")

    def get_status(self) -> ProviderStatus:
        """Return the current provider status."""
        return ProviderStatus(
            name=self.active_provider,
            model=self.active_model,
            available=self._active_provider is not None,
        )

    # ── Core Inference ─────────────────────────────────────────────────────

    def call_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        """
        Send a prompt to the active LLM provider and parse JSON response.
        Falls back through the provider chain on failure.
        Returns None if all providers fail.
        """
        providers = self._build_fallback_chain()

        for provider_name in providers:
            try:
                result = self._call_provider(provider_name, system_prompt, user_prompt)
                if result is not None:
                    # Update active provider on success
                    self._active_provider = provider_name
                    return result
            except Exception:
                continue

        return None

    def call_text(self, system_prompt: str, user_prompt: str) -> str | None:
        """
        Send a prompt to the active LLM provider and return raw text response.
        Falls back through the provider chain on failure.
        """
        providers = self._build_fallback_chain()

        for provider_name in providers:
            try:
                result = self._call_provider_text(provider_name, system_prompt, user_prompt)
                if result is not None:
                    # Update active provider on success
                    self._active_provider = provider_name
                    return result
            except Exception:
                continue

        return None

    def _call_provider_text(self, provider: str, system_prompt: str, user_prompt: str) -> str | None:
        """Dispatch text prompt to the correct provider backend."""
        if provider == self.GEMINI:
            return self._call_gemini_text(system_prompt, user_prompt)
        elif provider == self.OPENROUTER:
            return self._call_openrouter_text(system_prompt, user_prompt)
        elif provider == self.OLLAMA:
            return self._call_ollama_text(system_prompt, user_prompt)
        return None

    def _call_gemini_text(self, system_prompt: str, user_prompt: str) -> str | None:
        api_key = self._google_api_key
        model = self._gemini_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {"role": "user", "parts": [{"text": user_prompt}]}
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2048,
            }
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        candidates = body.get("candidates", [])
        if not candidates:
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return None

        return parts[0].get("text", "").strip()

    def _call_openrouter_text(self, system_prompt: str, user_prompt: str) -> str | None:
        api_key = self._openrouter_api_key
        model = self._openrouter_model
        url = "https://openrouter.ai/api/v1/chat/completions"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 2048
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("HTTP-Referer", "https://patchguard.ai")
        req.add_header("X-Title", "PatchGuard AI")

        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        choices = body.get("choices", [])
        if not choices:
            return None

        return choices[0].get("message", {}).get("content", "").strip()

    def _call_ollama_text(self, system_prompt: str, user_prompt: str) -> str | None:
        model = self._ollama_model
        url = f"{self._ollama_host}/api/chat"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 2048
            }
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        return body.get("message", {}).get("content", "").strip()

    def _build_fallback_chain(self) -> list[str]:
        """Build ordered list of providers to try."""
        chain = []
        if self._google_api_key and self._google_api_key != "dummy":
            chain.append(self.GEMINI)
        if self._openrouter_api_key and self._openrouter_api_key != "dummy":
            chain.append(self.OPENROUTER)
        chain.append(self.OLLAMA)
        return chain

    def _call_provider(self, provider: str, system_prompt: str, user_prompt: str) -> dict | None:
        """Dispatch to the correct provider backend."""
        if provider == self.GEMINI:
            return self._call_gemini(system_prompt, user_prompt)
        elif provider == self.OPENROUTER:
            return self._call_openrouter(system_prompt, user_prompt)
        elif provider == self.OLLAMA:
            return self._call_ollama(system_prompt, user_prompt)
        return None

    # ── Gemini Provider ────────────────────────────────────────────────────

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> dict | None:
        """Call Google Gemini API using REST (no SDK dependency)."""
        api_key = self._google_api_key
        model = self._gemini_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt + "\nYour response must be a single valid JSON block and nothing else."}]
            },
            "contents": [
                {"role": "user", "parts": [{"text": user_prompt}]}
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            }
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        # Extract text from Gemini response
        candidates = body.get("candidates", [])
        if not candidates:
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return None

        content = parts[0].get("text", "").strip()
        return self._parse_json_response(content)

    # ── OpenRouter Provider ────────────────────────────────────────────────

    def _call_openrouter(self, system_prompt: str, user_prompt: str) -> dict | None:
        """Call OpenRouter API using REST."""
        api_key = self._openrouter_api_key
        model = self._openrouter_model
        url = "https://openrouter.ai/api/v1/chat/completions"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt + "\nYour response must be a single valid JSON block and nothing else."},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 2048
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("HTTP-Referer", "https://patchguard.ai")
        req.add_header("X-Title", "PatchGuard AI")

        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        choices = body.get("choices", [])
        if not choices:
            return None

        content = choices[0].get("message", {}).get("content", "").strip()
        return self._parse_json_response(content)

    # ── Ollama Provider ────────────────────────────────────────────────────

    def _call_ollama(self, system_prompt: str, user_prompt: str) -> dict | None:
        """Call local Ollama API using REST."""
        model = self._ollama_model
        url = f"{self._ollama_host}/api/chat"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt + "\nYour response must be a single valid JSON block and nothing else."},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 2048
            }
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        content = body.get("message", {}).get("content", "").strip()
        if not content:
            return None
        return self._parse_json_response(content)

    # ── Response Parsing ───────────────────────────────────────────────────

    @staticmethod
    def _parse_json_response(content: str) -> dict | None:
        """Extract and parse JSON from LLM response text."""
        if not content:
            return None

        # Try direct parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code blocks
        if "```" in content:
            match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass

        # Try finding JSON braces
        start = content.find("{")
        end = content.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(content[start:end])
            except json.JSONDecodeError:
                pass

        return None


# ── Singleton Provider Instance ────────────────────────────────────────────

_provider_instance: ModelProvider | None = None


def get_provider() -> ModelProvider:
    """Get or create the global ModelProvider singleton."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = ModelProvider()
    return _provider_instance


def reset_provider():
    """Reset the singleton provider (useful after env var changes)."""
    global _provider_instance
    _provider_instance = None
