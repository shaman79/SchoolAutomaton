"""Education-system (curriculum) registry + the volatile-tail ``curriculum_directive``.

The learner selects a region locale (settings); it is whitelisted here and used ONLY to build the
trailing user message — the cached system prefix (``pedagogy.py``) is never touched, so prompt caching
stays byte-identical (SPEC §5 invariant #4).

The registry data lives in ``app/data/curricula.yaml`` (loaded once at import). A ``None`` / unknown
locale yields no directive (generic behaviour, identical to before this feature).
"""

from __future__ import annotations

from pathlib import Path

import yaml

_CURRICULA_YAML = Path(__file__).resolve().parents[2] / "data" / "curricula.yaml"


def _load() -> dict[str, dict]:
    if not _CURRICULA_YAML.is_file():  # pragma: no cover - defensive; the file ships with the app
        return {}
    data = yaml.safe_load(_CURRICULA_YAML.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


# Loaded once at import (deterministic; only ever read).
CURRICULA: dict[str, dict] = _load()

# Bare-language fallbacks: a bare code maps to a region only when there is a single sensible variant.
# 'en' is ambiguous (US vs GB) → stays None (generic) until the learner picks a region.
_BARE_LANG_DEFAULT: dict[str, str] = {"cs": "cs-CZ"}


def normalize_education_locale(raw: str | None) -> str | None:
    """Whitelist a client-supplied locale to a known education-system key, else ``None`` (generic).

    Accepts case/separator variants ('en_us', 'EN-US' → 'en-US'). Trusted, constrained input — this is
    the ONLY place a learner-chosen locale is admitted into generation, so anything unrecognised is
    dropped rather than guessed."""
    if not raw:
        return None
    token = raw.strip().replace("_", "-")
    if not token:
        return None
    parts = token.split("-")
    lang = parts[0].lower()
    if len(parts) >= 2 and parts[1]:
        canonical = f"{lang}-{parts[1].upper()}"
        if canonical in CURRICULA:
            return canonical
        return None
    # Bare language code (no region).
    return _BARE_LANG_DEFAULT.get(lang)


def base_language(education_locale: str | None) -> str | None:
    """The ISO-639-1 output language for a (normalized) education locale, or ``None`` if unknown."""
    if not education_locale:
        return None
    profile = CURRICULA.get(education_locale)
    if profile and profile.get("language"):
        return str(profile["language"]).lower()
    return education_locale.split("-")[0].lower() or None


def country_of(education_locale: str | None) -> str | None:
    """The ISO-3166 country for a (normalized) education locale, for crisis-resource localization."""
    if not education_locale:
        return None
    profile = CURRICULA.get(education_locale)
    if profile and profile.get("country"):
        return str(profile["country"]).upper()
    parts = education_locale.split("-")
    return parts[1].upper() if len(parts) >= 2 and parts[1] else None


def _grade_value(grade_band) -> str:
    return grade_band.value if hasattr(grade_band, "value") else str(grade_band or "")


def curriculum_directive(education_locale: str | None, grade_band) -> str:
    """Volatile-tail guidance pinning the education system. Empty string for a generic/unknown locale.

    Names the framework, the locale's name for this grade band, and spelling/units/currency/date/
    example conventions so generated content follows that system. Goes ONLY in the trailing user
    message — never the cached prefix."""
    profile = CURRICULA.get(education_locale or "")
    if not profile:
        return ""
    grade = _grade_value(grade_band)
    grade_name = (profile.get("grade_naming") or {}).get(grade)
    lines = [
        "Education system (follow precisely):",
        f"- Align the content to {profile['framework']}.",
    ]
    if grade_name:
        lines.append(f"- Refer to this level using its local name: \"{grade_name}\".")
    if profile.get("spelling"):
        lines.append(f"- Write in {profile['spelling']}.")
    if profile.get("units"):
        lines.append(f"- Measurements: use {profile['units']}.")
    if profile.get("currency"):
        lines.append(f"- Money: use {profile['currency']}.")
    if profile.get("date_format"):
        lines.append(f"- Dates: write as {profile['date_format']}.")
    if profile.get("conventions"):
        lines.append(f"- {profile['conventions']}")
    return "\n".join(lines)
