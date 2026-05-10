import os

from openai import OpenAI

from util import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL = "gpt-5.5"


def get_model():
    """Get the OpenAI model to use."""
    return os.getenv("OPENAI_MODEL", DEFAULT_MODEL)


def _get_reasoning():
    effort = os.getenv("OPENAI_REASONING_EFFORT")
    if not effort:
        return None
    return {"effort": effort}


def _get_text_options():
    verbosity = os.getenv("OPENAI_TEXT_VERBOSITY")
    if not verbosity:
        return None
    return {"verbosity": verbosity}


def chat_completion(system_prompt, user_prompt, max_tokens=4096):
    """
    Send a text generation request to OpenAI using the official SDK.
    Returns the assistant's response text.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set")

    model = get_model()
    client = OpenAI(api_key=api_key)

    payload = {
        "model": model,
        "instructions": system_prompt,
        "input": user_prompt,
        "max_output_tokens": max_tokens,
    }

    reasoning = _get_reasoning()
    if reasoning:
        payload["reasoning"] = reasoning

    text = _get_text_options()
    if text:
        payload["text"] = text

    logger.info(
        "Before OpenAI SDK call: "
        f"model={model}, max_output_tokens={max_tokens}, prompt_chars={len(user_prompt)}"
    )

    response = client.responses.create(**payload)
    content = response.output_text

    if not content:
        logger.error(
            "OpenAI response did not include output_text. "
            f"response_id={getattr(response, 'id', None)!r}, "
            f"status={getattr(response, 'status', None)!r}"
        )
        raise RuntimeError("OpenAI response did not include any solution content")

    logger.info(f"OpenAI response received from {model} ({len(content)} chars)")
    logger.info(f"OpenAI response:\n{content}")

    return content
