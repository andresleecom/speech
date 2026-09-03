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


def test_leading_digit_does_not_capitalize_later_letter():
    assert clean_text("3 apples", "basic") == "3 apples"


def test_abbreviation_and_shell_command_are_not_mid_capitalized():
    # Leading letter at index 0 still gets sentence-start capitalization.
    # Letters after the abbreviation or first word must not be forced uppercase.
    assert clean_text("e.g. foo", "basic") == "E.g. foo"
    assert clean_text("git status", "basic") == "Git status"
    assert clean_text("e.g. foo", "basic") != "e.G. Foo"
    assert clean_text("git status", "basic") != "Git Status"


def test_hola_capitalizes_first_letter():
    assert clean_text("hola", "basic") == "Hola"


def test_trailing_space_appended_after_sentence_punctuation():
    assert clean_text("Hello world.", "basic", append_trailing_space=True) == "Hello world. "
    assert clean_text("Hello world!", "basic", append_trailing_space=True) == "Hello world! "
    assert clean_text("Hello world?", "basic", append_trailing_space=True) == "Hello world? "
    assert clean_text("Hello world…", "basic", append_trailing_space=True) == "Hello world… "


def test_trailing_space_off_by_default_and_when_disabled():
    assert clean_text("Hello world.", "basic") == "Hello world."
    assert (
        clean_text("Hello world.", "basic", append_trailing_space=False) == "Hello world."
    )


def test_trailing_space_never_in_none_mode():
    assert clean_text("Hello world.", "none", append_trailing_space=True) == "Hello world."


def test_newline_commands_off_by_default():
    assert clean_text("hello new line world", "basic") == "Hello new line world"


def test_newline_commands_english():
    assert (
        clean_text("hello new line world", "basic", newline_commands=True)
        == "Hello\nworld"
    )
    assert (
        clean_text("hello new paragraph world", "basic", newline_commands=True)
        == "Hello\n\nworld"
    )


def test_newline_commands_spanish():
    assert (
        clean_text("hola nueva línea mundo", "basic", newline_commands=True)
        == "Hola\nmundo"
    )
    assert (
        clean_text("hola punto y aparte mundo", "basic", newline_commands=True)
        == "Hola\n\nmundo"
    )


def test_newline_commands_tolerate_surrounding_punctuation():
    assert clean_text("new line.", "basic", newline_commands=True) == "\n"
    assert (
        clean_text("hello new line. world", "basic", newline_commands=True)
        == "Hello\nworld"
    )
