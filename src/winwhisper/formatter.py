from __future__ import annotations

import os
import re

from .logger import get_logger

CLEANUP_PROMPT = (
    "Clean up this speech transcription while preserving the original language.\n"
    "Fix punctuation, capitalization, spacing, and obvious speech disfluencies.\n"
    "Do not translate.\n"
    "Do not add new ideas.\n"
    "Do not explain anything.\n"
    "Return only the cleaned text."
)

_SPACE_RE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([.,!?;:])")


def clean_text(text: str, mode: str) -> str:
    if mode == "none":
        return text
    if mode == "basic":
        return _basic_cleanup(text)
    if mode == "llm":
        return _llm_cleanup(text)
    raise ValueError(f"Unsupported cleanup mode: {mode}")


def _basic_cleanup(text: str) -> str:
    cleaned = text.strip()
    cleaned = _SPACE_RE.sub(" ", cleaned)
    cleaned = _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", cleaned)
    return _uppercase_first_alphabetic(cleaned)


def _uppercase_first_alphabetic(text: str) -> str:
    for index, char in enumerate(text):
        if char.isalpha():
            return text[:index] + char.upper() + text[index + 1 :]
    return text


def _llm_cleanup(text: str) -> str:
    logger = get_logger(__name__)

    if not os.getenv("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY is not set; falling back to basic cleanup.")
        return _basic_cleanup(text)

    try:
        from openai import OpenAI

        client = OpenAI()
        response = client.chat.completions.create(
            model=os.getenv("WINWHISPER_OPENAI_CLEANUP_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": CLEANUP_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
        )
        cleaned = response.choices[0].message.content
        if not cleaned:
            logger.warning("LLM cleanup returned no text; falling back to basic cleanup.")
            return _basic_cleanup(text)
        return cleaned.strip()
    except Exception as exc:
        logger.warning(
            "LLM cleanup failed with %s; falling back to basic cleanup.",
            exc.__class__.__name__,
        )
        return _basic_cleanup(text)
