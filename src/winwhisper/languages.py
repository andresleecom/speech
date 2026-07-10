"""Canonical language choices supported by the bundled Whisper integration."""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final


AUTO_LANGUAGE_MODE: Final = "auto"
QUICK_LANGUAGE_SLOT_COUNT: Final = 3
LanguageMode = str
LanguageFavorite = LanguageMode | None


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


@dataclass(frozen=True, slots=True)
class Language:
    code: str
    name: str


# Faster-whisper accepts these Whisper language codes. Keep this catalog local so
# opening settings never imports or loads the transcription model.
SUPPORTED_LANGUAGES: tuple[Language, ...] = (
    Language("af", "Afrikaans"),
    Language("am", "Amharic"),
    Language("ar", "Arabic"),
    Language("as", "Assamese"),
    Language("az", "Azerbaijani"),
    Language("ba", "Bashkir"),
    Language("be", "Belarusian"),
    Language("bg", "Bulgarian"),
    Language("bn", "Bengali"),
    Language("bo", "Tibetan"),
    Language("br", "Breton"),
    Language("bs", "Bosnian"),
    Language("ca", "Catalan"),
    Language("cs", "Czech"),
    Language("cy", "Welsh"),
    Language("da", "Danish"),
    Language("de", "German"),
    Language("el", "Greek"),
    Language("en", "English"),
    Language("es", "Spanish"),
    Language("et", "Estonian"),
    Language("eu", "Basque"),
    Language("fa", "Persian"),
    Language("fi", "Finnish"),
    Language("fo", "Faroese"),
    Language("fr", "French"),
    Language("gl", "Galician"),
    Language("gu", "Gujarati"),
    Language("ha", "Hausa"),
    Language("haw", "Hawaiian"),
    Language("he", "Hebrew"),
    Language("hi", "Hindi"),
    Language("hr", "Croatian"),
    Language("ht", "Haitian Creole"),
    Language("hu", "Hungarian"),
    Language("hy", "Armenian"),
    Language("id", "Indonesian"),
    Language("is", "Icelandic"),
    Language("it", "Italian"),
    Language("ja", "Japanese"),
    Language("jw", "Javanese"),
    Language("ka", "Georgian"),
    Language("kk", "Kazakh"),
    Language("km", "Khmer"),
    Language("kn", "Kannada"),
    Language("ko", "Korean"),
    Language("la", "Latin"),
    Language("lb", "Luxembourgish"),
    Language("ln", "Lingala"),
    Language("lo", "Lao"),
    Language("lt", "Lithuanian"),
    Language("lv", "Latvian"),
    Language("mg", "Malagasy"),
    Language("mi", "Maori"),
    Language("mk", "Macedonian"),
    Language("ml", "Malayalam"),
    Language("mn", "Mongolian"),
    Language("mr", "Marathi"),
    Language("ms", "Malay"),
    Language("mt", "Maltese"),
    Language("my", "Myanmar"),
    Language("ne", "Nepali"),
    Language("nl", "Dutch"),
    Language("nn", "Nynorsk"),
    Language("no", "Norwegian"),
    Language("oc", "Occitan"),
    Language("pa", "Punjabi"),
    Language("pl", "Polish"),
    Language("ps", "Pashto"),
    Language("pt", "Portuguese"),
    Language("ro", "Romanian"),
    Language("ru", "Russian"),
    Language("sa", "Sanskrit"),
    Language("sd", "Sindhi"),
    Language("si", "Sinhala"),
    Language("sk", "Slovak"),
    Language("sl", "Slovenian"),
    Language("sn", "Shona"),
    Language("so", "Somali"),
    Language("sq", "Albanian"),
    Language("sr", "Serbian"),
    Language("su", "Sundanese"),
    Language("sv", "Swedish"),
    Language("sw", "Swahili"),
    Language("ta", "Tamil"),
    Language("te", "Telugu"),
    Language("tg", "Tajik"),
    Language("th", "Thai"),
    Language("tk", "Turkmen"),
    Language("tl", "Tagalog"),
    Language("tr", "Turkish"),
    Language("tt", "Tatar"),
    Language("uk", "Ukrainian"),
    Language("ur", "Urdu"),
    Language("uz", "Uzbek"),
    Language("vi", "Vietnamese"),
    Language("yi", "Yiddish"),
    Language("yo", "Yoruba"),
    Language("zh", "Chinese"),
    Language("yue", "Cantonese"),
)

# These make the tray quick to scan. The full searchable settings dialog offers
# every code above.
DEFAULT_TRAY_LANGUAGE_MODES: Final[tuple[LanguageMode, ...]] = (
    "en",
    "es",
    "pt",
    "fr",
    "de",
    "it",
    "nl",
    "zh",
    "ja",
    "ko",
    "ar",
    "hi",
    "ru",
    "tr",
    "pl",
    "id",
)

# The first two slots deliberately preserve the previous English and Spanish
# quick-hotkey behavior. The third slot is available when the user pins another
# language.
DEFAULT_LANGUAGE_FAVORITES: Final[tuple[LanguageFavorite, ...]] = (
    "en",
    "es",
    None,
)

_LANGUAGE_BY_CODE = {language.code: language for language in SUPPORTED_LANGUAGES}
_LANGUAGE_BY_NAME = {
    _normalize_name(language.name): language.code for language in SUPPORTED_LANGUAGES
}
_AUTO_ALIASES = frozenset({"auto", "autodetect", "automatic", "detectlanguage"})
_UNPINNED_ALIASES = frozenset({"", "disabled", "none", "notpinned", "off"})


def normalize_language_mode(value: object) -> LanguageMode | None:
    """Return a canonical Whisper language code, ``auto``, or ``None``."""
    if not isinstance(value, str):
        return None

    stripped = value.strip()
    normalized_name = _normalize_name(stripped)
    if normalized_name in _AUTO_ALIASES:
        return AUTO_LANGUAGE_MODE

    code = stripped.casefold()
    if code in _LANGUAGE_BY_CODE:
        return code

    if stripped.endswith(")") and "(" in stripped:
        possible_code = stripped.rsplit("(", 1)[1][:-1].strip().casefold()
        if possible_code in _LANGUAGE_BY_CODE:
            return possible_code

    return _LANGUAGE_BY_NAME.get(normalized_name)


def is_supported_language_mode(value: object) -> bool:
    return normalize_language_mode(value) is not None


def normalize_language_favorites(value: object) -> tuple[LanguageFavorite, ...]:
    """Validate up to three distinct non-auto languages for quick actions."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("Language favorites must be a list of up to three languages.")
    if len(value) > QUICK_LANGUAGE_SLOT_COUNT:
        raise ValueError(
            f"Choose at most {QUICK_LANGUAGE_SLOT_COUNT} language favorites."
        )

    favorites: list[LanguageFavorite] = []
    seen: set[LanguageMode] = set()
    for entry in value:
        if entry is None:
            favorites.append(None)
            continue
        if isinstance(entry, str) and _normalize_name(entry) in _UNPINNED_ALIASES:
            favorites.append(None)
            continue
        normalized = normalize_language_mode(entry)
        if normalized is None or normalized == AUTO_LANGUAGE_MODE:
            raise ValueError("Each language favorite must be a supported language.")
        if normalized in seen:
            raise ValueError("Choose each language favorite only once.")
        seen.add(normalized)
        favorites.append(normalized)

    favorites.extend([None] * (QUICK_LANGUAGE_SLOT_COUNT - len(favorites)))
    return tuple(favorites)


def language_name(mode: object) -> str:
    normalized = normalize_language_mode(mode)
    if normalized == AUTO_LANGUAGE_MODE:
        return "Auto-detect"
    if normalized is not None:
        return _LANGUAGE_BY_CODE[normalized].name
    return str(mode)


def language_choice_label(mode: object) -> str:
    normalized = normalize_language_mode(mode)
    if normalized == AUTO_LANGUAGE_MODE:
        return "Auto-detect"
    if normalized is not None:
        language = _LANGUAGE_BY_CODE[normalized]
        return f"{language.name} ({language.code})"
    return str(mode)


def language_choice_labels() -> tuple[str, ...]:
    languages = sorted(SUPPORTED_LANGUAGES, key=lambda language: language.name)
    return (
        "Auto-detect",
        *(f"{language.name} ({language.code})" for language in languages),
    )


def filter_language_choice_labels(query: str) -> tuple[str, ...]:
    normalized_query = query.strip().casefold()
    if not normalized_query:
        return language_choice_labels()
    return tuple(
        label
        for label in language_choice_labels()
        if normalized_query in label.casefold()
    )


def tray_language_modes(
    current_mode: object,
    favorites: object = DEFAULT_LANGUAGE_FAVORITES,
) -> tuple[LanguageMode, ...]:
    current = normalize_language_mode(current_mode)
    modes: list[LanguageMode] = []
    try:
        normalized_favorites = normalize_language_favorites(favorites)
    except ValueError:
        normalized_favorites = DEFAULT_LANGUAGE_FAVORITES
    for favorite in normalized_favorites:
        if favorite is not None and favorite not in modes:
            modes.append(favorite)
    for featured_mode in DEFAULT_TRAY_LANGUAGE_MODES:
        if featured_mode not in modes:
            modes.append(featured_mode)
    if current and current != AUTO_LANGUAGE_MODE and current not in modes:
        modes.append(current)
    return tuple(modes)
