"""The ONLY place the app talks to an AI model.

The model is treated as an outside text function: it gets text in and returns text out.
It has no database login, no tools and no way to call the app. Each provider is a small
adapter with one method, complete(system, messages) -> str.
"""
import os
import time

import streamlit as st

import src.config  # noqa: F401  (loads the .env file)

MAX_QUESTION_CHARS = 400
MAX_PER_HOUR = int(os.getenv("AGENT_MAX_PER_HOUR", "30"))


class LLMError(Exception):
    """Anything that stops us getting an answer from the model. Shown to users in plain words."""


class FakeProvider:
    """Scripted replies for testing. Each call returns the next reply. No network."""
    name = "fake"
    model = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system: str, messages: list, json_mode: bool = True) -> str:
        self.calls.append({"system": system, "messages": [dict(m) for m in messages]})
        if not self.replies:
            raise LLMError("The fake model has no more scripted replies.")
        return self.replies.pop(0)


class GeminiProvider:
    """Google Gemini through the official google-genai package. Needs GEMINI_API_KEY in .env."""
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise LLMError("The Gemini package is missing. Run: pip install google-genai") from e
        self._types = types
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def _generate(self, contents, config):
        """Retry briefly when Google says it is overloaded (503), so a short spike does not fail the question."""
        delays = (2, 5)
        for i in range(len(delays) + 1):
            try:
                return self.client.models.generate_content(model=self.model, contents=contents, config=config)
            except Exception as e:
                temporary = "503" in str(e) or "UNAVAILABLE" in str(e)
                if not temporary or i == len(delays):
                    raise
                time.sleep(delays[i])

    def complete(self, system: str, messages: list, json_mode: bool = True) -> str:
        t = self._types
        contents = [t.Content(role="model" if m["role"] == "assistant" else "user",
                              parts=[t.Part(text=m["content"])]) for m in messages]
        config = t.GenerateContentConfig(system_instruction=system, temperature=0,
                                         response_mime_type="application/json" if json_mode else "text/plain")
        try:
            resp = self._generate(contents, config)
            text = resp.text
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                raise LLMError("The AI service is very busy right now. Please try again in a minute.") from e
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                raise LLMError("The AI service is busy. Please wait a minute and try again.") from e
            msg = "The AI service is not available right now."
            if os.getenv("AGENT_DEBUG") == "1":
                msg += f" ({type(e).__name__}: {e})"
            raise LLMError(msg) from e
        if not text:
            raise LLMError("The AI service returned an empty answer.")
        return text


def _raise_friendly(e: Exception):
    """Same plain-words errors for every provider. Raw details only when AGENT_DEBUG=1."""
    code = getattr(e, "status_code", None)
    s = str(e)
    if code == 429 or "429" in s:
        raise LLMError("The AI service is busy. Please wait a minute and try again.") from e
    if code in (500, 502, 503, 529) or "UNAVAILABLE" in s or "overloaded" in s.lower():
        raise LLMError("The AI service is very busy right now. Please try again in a minute.") from e
    msg = "The AI service is not available right now."
    if os.getenv("AGENT_DEBUG") == "1":
        msg += f" ({type(e).__name__}: {e})"
    raise LLMError(msg) from e


class OpenAIProvider:
    """OpenAI-compatible API (OpenAI, Groq, Cerebras, Ollama). Needs OPENAI_API_KEY in .env."""
    name = "openai"

    def __init__(self, api_key: str, model: str):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMError("The OpenAI package is missing. Run: pip install openai") from e
        self.client = OpenAI(api_key=api_key, max_retries=2,
                             base_url=os.getenv("OPENAI_BASE_URL") or None)
        self.model = model

    def complete(self, system: str, messages: list, json_mode: bool = True) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model, **({"response_format": {"type": "json_object"}} if json_mode else {}),
                messages=[{"role": "system", "content": system}]
                         + [{"role": m["role"], "content": m["content"]} for m in messages])
            text = resp.choices[0].message.content
        except Exception as e:
            _raise_friendly(e)
        if not text:
            raise LLMError("The AI service returned an empty answer.")
        return text


def get_provider():
    """Chosen by LLM_PROVIDER in .env. Only providers the company has approved should be added."""
    name = os.getenv("LLM_PROVIDER", "").strip().lower()
    if name == "gemini":
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            raise LLMError("GEMINI_API_KEY is missing in the .env file.")
        return GeminiProvider(key, os.getenv("GEMINI_MODEL", "gemini-3-flash-preview").strip())
    if name == "openai":
        key = os.getenv("OPENAI_API_KEY", "").strip()
        model = os.getenv("OPENAI_MODEL", "").strip()
        if not key or not model:
            raise LLMError("OPENAI_API_KEY and OPENAI_MODEL must be set in the .env file.")
        return OpenAIProvider(key, model)
    raise LLMError(f"No AI provider is configured yet (LLM_PROVIDER='{name}').")


@st.cache_resource
def _hits() -> dict:
    return {}


def check_rate(username: str) -> None:
    """At most MAX_PER_HOUR questions per user per hour (kept in memory, resets on restart)."""
    now = time.time()
    h = _hits().setdefault(username, [])
    h[:] = [t for t in h if now - t < 3600]
    if len(h) >= MAX_PER_HOUR:
        raise LLMError("You have reached the hourly limit of AI questions. Please try again later.")
    h.append(now)

