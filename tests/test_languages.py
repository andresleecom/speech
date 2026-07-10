import pytest

from winwhisper.languages import (
    AUTO_LANGUAGE_MODE,
    DEFAULT_LANGUAGE_FAVORITES,
    DEFAULT_TRAY_LANGUAGE_MODES,
    SUPPORTED_LANGUAGES,
    filter_language_choice_labels,
    language_choice_label,
    language_choice_labels,
    language_name,
    normalize_language_favorites,
    normalize_language_mode,
    tray_language_modes,
)


def test_catalog_matches_supported_whisper_language_code_count():
    codes = [language.code for language in SUPPORTED_LANGUAGES]

    assert len(codes) == 100
    assert len(codes) == len(set(codes))
    assert {"en", "es", "fr", "pt", "zh", "yue"} <= set(codes)


def test_catalog_stays_in_sync_with_faster_whisper():
    from faster_whisper.tokenizer import _LANGUAGE_CODES

    assert tuple(language.code for language in SUPPORTED_LANGUAGES) == _LANGUAGE_CODES


def test_normalize_language_mode_accepts_codes_names_and_picker_labels():
    assert normalize_language_mode("auto") == AUTO_LANGUAGE_MODE
    assert normalize_language_mode("Auto-detect") == AUTO_LANGUAGE_MODE
    assert normalize_language_mode("FR") == "fr"
    assert normalize_language_mode("French") == "fr"
    assert normalize_language_mode("French (fr)") == "fr"
    assert normalize_language_mode("Cantonese (yue)") == "yue"
    assert normalize_language_mode("not a language") is None


def test_language_labels_are_human_readable_and_searchable():
    choices = language_choice_labels()

    assert choices[0] == "Auto-detect"
    assert "French (fr)" in choices
    assert "Cantonese (yue)" in choices
    assert language_name("zh") == "Chinese"
    assert language_choice_label("zh") == "Chinese (zh)"
    assert filter_language_choice_labels("french") == ("French (fr)",)
    assert filter_language_choice_labels("(yue)") == ("Cantonese (yue)",)


def test_tray_languages_include_featured_languages_and_current_selection():
    assert tray_language_modes("auto") == DEFAULT_TRAY_LANGUAGE_MODES
    assert tray_language_modes("fr") == DEFAULT_TRAY_LANGUAGE_MODES
    assert tray_language_modes("yue")[-1] == "yue"


def test_language_favorites_normalize_and_prioritize_the_tray_menu():
    assert DEFAULT_LANGUAGE_FAVORITES == ("en", "es", None)
    assert normalize_language_favorites(["French (fr)", "Japanese", "Not pinned"]) == (
        "fr",
        "ja",
        None,
    )
    assert tray_language_modes("auto", ["fr", "ja", None])[:2] == ("fr", "ja")


def test_language_favorites_reject_auto_duplicates_and_too_many_values():
    with pytest.raises(ValueError, match="supported language"):
        normalize_language_favorites(["auto"])
    with pytest.raises(ValueError, match="only once"):
        normalize_language_favorites(["fr", "French"])
    with pytest.raises(ValueError, match="at most"):
        normalize_language_favorites(["en", "es", "fr", "ja"])
