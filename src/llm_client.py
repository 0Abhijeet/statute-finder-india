"""Single place the LLM client is built. Groq is reached through its
OpenAI-compatible endpoint, so swapping provider = changing base_url / key /
model env vars. Prompt, output shape and streaming-vs-not are Phase 5
decisions and deliberately not here."""
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()  # does not override variables already in the environment

_client = None

LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-20b")


def get_llm_client() -> AsyncOpenAI:
    """Lazy singleton: a missing key fails when first used, not at import."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.environ["LLM_API_KEY"],
            base_url=os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
            timeout=float(os.environ.get("LLM_TIMEOUT", "60")),  # a stalled connection must not hang for the 10-minute default
            max_retries=1,
        )
    return _client


async def create_with_retry(client, **kwargs):
    """chat.completions.create with retries for transient errors only.

    Groq's free tier for openai/gpt-oss-20b is 8,000 tokens per minute (seen in the
    x-ratelimit-limit-tokens header), so bursts of calls get HTTP 429. Retries on 429,
    5xx and Groq's empty-output 400 (json_validate_failed), sleeping 20 s then 45 s.
    Anything else (including non-HTTP errors) is raised immediately."""
    import asyncio

    last = None
    for delay in (0, 20, 45):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await client.chat.completions.create(**kwargs)
        except Exception as e:
            status = getattr(e, "status_code", None)
            transient = status == 429 or (status is not None and status >= 500) or (
                status == 400 and "json_validate_failed" in str(e))
            if not transient:
                raise
            last = e
    raise last


def reasoning_kwargs() -> dict:
    """gpt-oss (Groq) is a reasoning model and is called with reasoning_effort="low" so
    it does not spend the token budget thinking. Models without a thinking mode (for
    example qwen2.5 on Ollama) reject the parameter, so set LLM_REASONING_EFFORT="" to omit it."""
    v = os.environ.get("LLM_REASONING_EFFORT", "low")
    return {"extra_body": {"reasoning_effort": v}} if v else {}
