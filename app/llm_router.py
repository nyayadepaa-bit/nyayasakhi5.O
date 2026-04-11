"""
app/llm_router.py
------------------
Fallback LLM routing chain with retry logic:
  Groq (retry ×3) → OpenRouter → Gemini (try multiple models) → Ollama

Handles 429 rate limits with exponential backoff on Groq.
Tries multiple Gemini model versions as fallback.
"""

import logging
import time
from typing import Optional

from app.config import (
    GROQ_API_KEY,    GROQ_MODEL,
    OPENROUTER_API_KEY, OPENROUTER_MODEL,
    GEMINI_API_KEY,  GEMINI_MODEL,
    OLLAMA_URL,      OLLAMA_MODEL,
    LLM_TEMPERATURE, LLM_MAX_TOKENS,
)

logger = logging.getLogger(__name__)

# Track provider failures for monitoring
_failure_log: list[dict] = []

# Gemini fallback models to try in order if primary fails
GEMINI_FALLBACK_MODELS = [
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-pro",
    "gemini-2.0-flash-lite",
]

# Effective max tokens — bump for longer prediction prompts
EFFECTIVE_MAX_TOKENS = max(LLM_MAX_TOKENS, 3000)


def _try_groq(messages: list[dict], temperature: float, max_tokens: int) -> Optional[str]:
    """Try Groq with up to 3 retries on rate-limit (429). Exponential backoff."""
    if not GROQ_API_KEY:
        return None
    from groq import Groq, APIStatusError
    client = Groq(api_key=GROQ_API_KEY)
    for attempt in range(3):
        try:
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return completion.choices[0].message.content.strip()
        except APIStatusError as e:
            if e.status_code == 429:
                wait = 2 ** attempt          # 1s, 2s, 4s
                logger.warning(f"Groq rate-limited (attempt {attempt+1}/3). Waiting {wait}s…")
                time.sleep(wait)
                continue
            _failure_log.append({"provider": "groq", "error": str(e), "time": time.time()})
            logger.warning(f"Groq API error: {e}")
            return None
        except Exception as e:
            _failure_log.append({"provider": "groq", "error": str(e), "time": time.time()})
            logger.warning(f"Groq failed: {e}")
            return None
    _failure_log.append({"provider": "groq", "error": "Rate limit — all retries exhausted", "time": time.time()})
    logger.warning("Groq: all 3 retries exhausted after rate limiting.")
    return None


def _try_openrouter(messages: list[dict], temperature: float, max_tokens: int) -> Optional[str]:
    """Try OpenRouter. Falls back to a free backup model if primary fails."""
    if not OPENROUTER_API_KEY:
        return None
    models_to_try = [
        OPENROUTER_MODEL,
        "meta-llama/llama-3.1-8b-instruct:free",
        "mistralai/mistral-7b-instruct:free",
    ]
    import requests
    for model in models_to_try:
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=60,
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"].strip()
            if text:
                logger.info(f"OpenRouter: succeeded with model {model}")
                return text
        except Exception as e:
            logger.warning(f"OpenRouter model {model} failed: {e}")
            _failure_log.append({"provider": f"openrouter:{model}", "error": str(e), "time": time.time()})
            continue
    _failure_log.append({"provider": "openrouter", "error": "All models exhausted", "time": time.time()})
    return None


def _try_gemini(messages: list[dict], temperature: float, max_tokens: int) -> Optional[str]:
    """Try Google Gemini — tries primary model then multiple fallbacks."""
    if not GEMINI_API_KEY:
        return None

    prompt = "\n".join(
        f"{'System' if m['role'] == 'system' else 'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in messages
    )

    models_to_try = [GEMINI_MODEL] + GEMINI_FALLBACK_MODELS
    # deduplicate preserving order
    seen = set()
    models_to_try = [m for m in models_to_try if not (m in seen or seen.add(m))]

    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        logger.warning(f"Gemini SDK init failed: {e}")
        return None

    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )
            response = model.generate_content(prompt)
            text = response.text.strip()
            if text:
                logger.info(f"Gemini: succeeded with model {model_name}")
                return text
        except Exception as e:
            logger.warning(f"Gemini model {model_name} failed: {e}")
            _failure_log.append({"provider": f"gemini:{model_name}", "error": str(e), "time": time.time()})
            continue

    _failure_log.append({"provider": "gemini", "error": "All models exhausted", "time": time.time()})
    return None


def _try_ollama(messages: list[dict], temperature: float, max_tokens: int) -> Optional[str]:
    """Try local Ollama (last resort)."""
    import requests
    try:
        # First check if Ollama is actually up
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).raise_for_status()

        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["message"]["content"].strip()
    except Exception as e:
        _failure_log.append({"provider": "ollama", "error": str(e), "time": time.time()})
        logger.warning(f"Ollama failed: {e}")
        return None


# ── Provider Chain ────────────────────────────────────────
PROVIDERS = [
    ("Groq",        _try_groq),
    ("OpenRouter",  _try_openrouter),
    ("Gemini",      _try_gemini),
    ("Ollama",      _try_ollama),
]


def generate(
    prompt: str,
    system_prompt: str = "",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> dict:
    """
    Generate LLM response with automatic fallback routing.
    Groq retries up to 3x on rate limits before moving to next provider.
    """
    temp   = temperature if temperature is not None else LLM_TEMPERATURE
    tokens = max_tokens  if max_tokens  is not None else EFFECTIVE_MAX_TOKENS

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    for name, provider_fn in PROVIDERS:
        logger.info(f"Trying LLM provider: {name}…")
        result = provider_fn(messages, temp, tokens)
        if result:
            logger.info(f"✓ {name} responded successfully")
            return {"text": result, "provider": name, "error": None}

    # All providers failed — return a helpful message (not a generic error)
    error_msg = "All LLM providers exhausted."
    logger.error(error_msg)
    return {
        "text": (
            "I'm having trouble reaching the AI service right now. "
            "Please wait 30 seconds and send your message again — "
            "this usually resolves on its own. "
            "If it keeps happening, please check your API keys in the `.env` file."
        ),
        "provider": None,
        "error": error_msg,
    }


def get_failure_log() -> list[dict]:
    """Get recent provider failures for monitoring."""
    return _failure_log[-20:]


def get_available_providers() -> dict[str, bool]:
    """Check which providers are configured."""
    return {
        "groq":        bool(GROQ_API_KEY),
        "openrouter":  bool(OPENROUTER_API_KEY),
        "gemini":      bool(GEMINI_API_KEY),
        "ollama":      True,
    }
