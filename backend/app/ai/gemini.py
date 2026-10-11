"""Minimal Gemini REST client: JSON in, JSON out, one `ai_calls` row per call.

Plain httpx instead of Google's SDK keeps dependencies small and makes the
free-tier error codes (429 = over quota) easy to handle.
"""

import json
import time
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models import AICall

API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class LLMError(Exception):
    """The call failed or returned something unusable."""


class LLMRateLimited(LLMError):
    """Free-tier quota reached (HTTP 429). Stop for this run; nothing is charged."""


class LLMClient:
    def __init__(self, client: httpx.Client, session: Session, api_key: str) -> None:
        self.client = client
        self.session = session
        self.api_key = api_key

    def generate_json(
        self,
        *,
        model: str,
        purpose: str,
        prompt_version: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float = 0.1,
    ) -> Any:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        call = AICall(purpose=purpose, model=model, prompt_version=prompt_version, ok=False)
        started = time.monotonic()
        try:
            response = self.client.post(
                f"{API_BASE}/models/{model}:generateContent",
                json=body,
                # Header, not ?key=, so the key never appears in logged URLs.
                headers={"x-goog-api-key": self.api_key},
                timeout=120,
            )
            if response.status_code == 429:
                raise LLMRateLimited("free-tier limit reached (HTTP 429)")
            if response.status_code == 404:
                raise LLMError(f"model {model!r} not found; check the model name in AI Studio")
            if response.status_code >= 400:
                raise LLMError(f"HTTP {response.status_code}: {response.text[:300]}")
            data = response.json()
            usage = data.get("usageMetadata", {})
            call.input_tokens = usage.get("promptTokenCount", 0)
            call.output_tokens = usage.get("candidatesTokenCount", 0)
            call.cache_read_tokens = usage.get("cachedContentTokenCount", 0)
            try:
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                result = json.loads(text)
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                reason = data.get("candidates", [{}])[0].get("finishReason", "unknown")
                raise LLMError(f"unusable response (finish reason: {reason})") from e
            call.ok = True
            return result
        except httpx.HTTPError as e:
            call.error = f"{type(e).__name__}: {e}"[:500]
            raise LLMError(call.error) from e
        except LLMError as e:
            call.error = str(e)[:500]
            raise
        finally:
            call.latency_ms = int((time.monotonic() - started) * 1000)
            call.cost_usd = 0  # free tier, no billing account
            self.session.add(call)
            self.session.commit()
