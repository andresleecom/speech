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

LLM_CLEANUP_TIMEOUT_SECONDS = 30.0

_SPACE_RE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([.,!?;:])")
_OPENING_PUNCTUATION = frozenset("¿¡([{\"'" + "«“‘")
_SENTENCE_ENDINGS = (".", "!", "?", "…")
_NEWLINE_COMMANDS: tuple[tuple[str, str], ...] = (
    ("new paragraph", "\n\n"),
    ("punto y aparte", "\n\n"),
    ("new line", "\n"),
    ("nueva línea", "\n"),
)
_SURROUNDING_PUNCT_CLASS = (
    r"¿¡\(\[\{" + "\"'" + r"«“‘.!?,;:…" + "\"'" + r"»”’\)\]\}"
)


def build_cleanup_prompt(vocabulary: list[str] | None = None) -> str:
    """The LLM cleanup system prompt, with the user's custom vocabulary if any."""
    terms = [term.strip() for term in (vocabulary or []) if term and term.strip()]
    if not terms:
        return CLEANUP_PROMPT
    glossary = ", ".join(terms)
    return (
        CLEANUP_PROMPT
        + "\nWhen a word sounds like one of these names or terms, use this exact "
        + f"spelling: {glossary}."
    )


def clean_text(
    text: str,
    mode: str,
    vocabulary: list[str] | None = None,
    *,
    append_trailing_space: bool = False,
    newline_commands: bool = False,
) -> str:
    if mode == "none":
        return text
    if mode == "basic":
        return _basic_cleanup(
            text,
            append_trailing_space=append_trailing_space,
            newline_commands=newline_commands,
        )
    if mode == "llm":
        return _llm_cleanup(
            text,
            vocabulary,
            append_trailing_space=append_trailing_space,
            newline_commands=newline_commands,
        )
    raise ValueError(f"Unsupported cleanup mode: {mode}")


def append_trailing_space_if_needed(text: str) -> str:
    """Append one space when text ends with sentence-ending punctuation."""
    if text.endswith(_SENTENCE_ENDINGS):
        return text + " "
    return text


def _basic_cleanup(
    text: str,
    *,
    append_trailing_space: bool = False,
    newline_commands: bool = False,
) -> str:
    cleaned = text.strip()
    cleaned = _SPACE_RE.sub(" ", cleaned)
    cleaned = _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", cleaned)
    if newline_commands:
        cleaned = _apply_newline_commands(cleaned)
    cleaned = _uppercase_first_alphabetic(cleaned)
    if append_trailing_space:
        cleaned = append_trailing_space_if_needed(cleaned)
    return cleaned


def _uppercase_first_alphabetic(text: str) -> str:
    for index, char in enumerate(text):
        if not char.isalpha():
            continue
        prefix = text[:index]
        if index == 0 or (prefix and all(c in _OPENING_PUNCTUATION for c in prefix)):
            return text[:index] + char.upper() + text[index + 1 :]
        return text
    return text


def _apply_newline_commands(text: str) -> str:
    result = text
    for phrase, replacement in _NEWLINE_COMMANDS:
        escaped = re.escape(phrase).replace(r"\ ", r"\s+")
        pattern = re.compile(
            rf"(?i)(?<!\w)[{_SURROUNDING_PUNCT_CLASS}]*\s*{escaped}\s*"
            rf"[{_SURROUNDING_PUNCT_CLASS}]*(?!\w)"
        )
        result = pattern.sub(replacement, result)
    result = re.sub(r"[^\S\n]*\n[^\S\n]*", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = re.sub(r"[^\S\n]{2,}", " ", result)
    return result.strip(" \t")


def _llm_cleanup(
    text: str,
    vocabulary: list[str] | None = None,
    *,
    append_trailing_space: bool = False,
    newline_commands: bool = False,
) -> str:
    logger = get_logger(__name__)

    if not os.getenv("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY is not set; falling back to basic cleanup.")
        return _basic_cleanup(
            text,
            append_trailing_space=append_trailing_space,
            newline_commands=newline_commands,
        )

    try:
        from openai import OpenAI

        client = OpenAI(timeout=LLM_CLEANUP_TIMEOUT_SECONDS)
        response = client.chat.completions.create(
            model=os.getenv("WINWHISPER_OPENAI_CLEANUP_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": build_cleanup_prompt(vocabulary)},
                {"role": "user", "content": text},
            ],
            temperature=0,
            timeout=LLM_CLEANUP_TIMEOUT_SECONDS,
        )
        cleaned = response.choices[0].message.content
        if not cleaned:
            logger.warning("LLM cleanup returned no text; falling back to basic cleanup.")
            return _basic_cleanup(
                text,
                append_trailing_space=append_trailing_space,
                newline_commands=newline_commands,
            )
        cleaned = cleaned.strip()
        if newline_commands:
            cleaned = _apply_newline_commands(cleaned)
        if append_trailing_space:
            cleaned = append_trailing_space_if_needed(cleaned)
        return cleaned
    except Exception as exc:
        logger.warning(
            "LLM cleanup failed with %s; falling back to basic cleanup.",
            exc.__class__.__name__,
        )
        return _basic_cleanup(
            text,
            append_trailing_space=append_trailing_space,
            newline_commands=newline_commands,
        )
