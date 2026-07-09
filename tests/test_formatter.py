from winwhisper.formatter import CLEANUP_PROMPT, build_cleanup_prompt, clean_text


def test_cleanup_prompt_without_vocabulary_is_unchanged():
    assert build_cleanup_prompt(None) == CLEANUP_PROMPT
    assert build_cleanup_prompt([]) == CLEANUP_PROMPT
    assert build_cleanup_prompt(["  ", ""]) == CLEANUP_PROMPT


def test_cleanup_prompt_includes_custom_vocabulary():
    prompt = build_cleanup_prompt(["README", " Claude Code "])

    assert prompt.startswith(CLEANUP_PROMPT)
    assert "README, Claude Code" in prompt


def test_basic_cleanup_accepts_vocabulary_argument():
    assert clean_text("hello world", "basic", ["README"]) == "Hello world"


def test_basic_english_capitalizes_first_character_only():
    text = "hey can you send john the report tomorrow morning please"

    assert clean_text(text, "basic") == (
        "Hey can you send john the report tomorrow morning please"
    )


def test_basic_spanish_capitalizes_first_character_only():
    text = "oye puedes mandar el reporte mañana por favor"

    assert clean_text(text, "basic") == "Oye puedes mandar el reporte mañana por favor"


def test_none_mode_passthrough():
    text = "  raw   transcription  "

    assert clean_text(text, "none") == text


def test_whitespace_collapse():
    assert clean_text(" hello \n\t world  ", "basic") == "Hello world"


def test_space_before_punctuation_removal():
    assert clean_text(" hello , world ! ", "basic") == "Hello, world!"


def test_spanish_inverted_question_mark_stays_before_capitalized_letter():
    assert clean_text("¿qué hora es?", "basic") == "¿Qué hora es?"
