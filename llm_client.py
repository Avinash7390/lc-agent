import os
import json

import requests

from util import get_logger

logger = get_logger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Common model aliases available through OpenRouter.
MODELS = {
    "free": "openai/gpt-oss-20b:free",
    "deepseek": "openai/gpt-oss-20b:free",
    "qwen": "qwen/qwen3-235b-a22b:free",
    "llama": "meta-llama/llama-4-maverick:free",
    "openai": "openai/gpt-5.5",
    "premium": "openai/gpt-5.1",
    "gpt-5.1": "openai/gpt-5.1",
    "gpt-5": "openai/gpt-5",
    "gpt-4o": "openai/gpt-4o",
    "gpt-4o-mini": "openai/gpt-4o-mini",
}


def get_model():
    """Get the model to use from env var, defaulting to the free router."""
    model_key = os.getenv("LLM_MODEL", "free").lower()

    if model_key in MODELS:
        return MODELS[model_key]

    # Allow passing a full model ID directly (e.g., "deepseek/deepseek-r1:free")
    return model_key


def chat_completion(system_prompt, user_prompt, max_tokens=4096):
    """
    Send a chat completion request to OpenRouter.
    Returns the assistant's response text.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY environment variable is not set")

    model = get_model()
    logger.info(f"Before LLM call: model={model}, max_tokens={max_tokens}, prompt_chars={len(user_prompt)}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/lc-potd-solver",
        "X-Title": "LC POTD Solver",
    }

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    logger.info("Calling LLM provider: OpenRouter chat completions")
    response = requests.post(
        OPENROUTER_API_URL,
        headers=headers,
        data=json.dumps(payload),
        timeout=120,
    )
    logger.info(f"After LLM HTTP response: status_code={response.status_code}")
    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(f"OpenRouter API error: {data['error']}")

    actual_model = data.get("model", model)
    choices = data.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    content = message.get("content")

    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )

    if not content:
        logger.error(
            "LLM response did not include message.content. "
            f"actual_model={actual_model}, finish_reason={choice.get('finish_reason')!r}, "
            f"message_keys={list(message.keys())}, choice_keys={list(choice.keys())}"
        )
        logger.error(f"Raw LLM response metadata: {json.dumps(data, default=str)[:2000]}")
        raise RuntimeError("LLM response did not include any solution content")

    logger.info(f"LLM response received from {actual_model} ({len(content)} chars)")
    logger.info(f"LLM response:\n{content}")

    return content
