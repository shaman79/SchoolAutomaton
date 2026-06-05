"""Layer 1 — deterministic preprocessing (SPEC §5). Pure, side-effect-free, and **cannot be injected**:
it only normalizes/strips bytes and runs cheap advisory regexes. It NEVER blocks a prompt on its own —
heuristic hits and the homoglyph flag only raise ``suspicion_score`` for the audit trail; the real
containment is the classifier + the deterministic ``validate.py`` layer.

Returns ``PreprocessResult(clean_text, removed_char_summary, suspicion_score, heuristic_hit_ids)``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

# --------------------------------------------------------------------------- character classes
# Zero-width space/non-joiner/joiner, word-joiner, BOM (U+200B-200D, U+2060, U+FEFF).
_INVISIBLE = frozenset("​‌‍⁠﻿")
# Bidi embeddings/overrides/isolates (U+202A-202E, U+2066-2069) — used to visually reorder text.
_BIDI = frozenset("‪‫‬‭‮⁦⁧⁨⁩")
# Allowed control chars (kept); everything else in C0/C1 is stripped.
_ALLOWED_CONTROL = frozenset("\n\t")

_PATTERNS_PATH = Path(__file__).resolve().parent.parent / "data" / "patterns.yaml"

# Scripts whose mixing with Latin within a single token signals homoglyph spoofing.
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_GREEK_RE = re.compile(r"[Ͱ-Ͽ]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_TOKEN_RE = re.compile(r"\S+")
# Horizontal whitespace: any Unicode whitespace except newline (NBSP, Zs, tab, FF, VT, ...).
_WS_RUN_RE = re.compile(r"[^\S\n]+")
_NEWLINE_RUN_RE = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class HeuristicRule:
    id: str
    pattern: re.Pattern[str]
    weight: float
    desc: str = ""


@dataclass
class PreprocessResult:
    """Output of Layer 1. ``clean_text`` is the only thing handed forward to the classifier."""

    clean_text: str
    removed_char_summary: dict[str, int] = field(default_factory=dict)
    suspicion_score: float = 0.0
    heuristic_hit_ids: list[str] = field(default_factory=list)
    homoglyph_mixing: bool = False

    def as_tuple(self) -> tuple[str, dict[str, int], float, list[str]]:
        """The (clean_text, removed_char_summary, suspicion_score, heuristic_hit_ids) contract tuple."""
        return (self.clean_text, self.removed_char_summary, self.suspicion_score, self.heuristic_hit_ids)


@lru_cache(maxsize=1)
def _load_rules() -> tuple[HeuristicRule, ...]:
    """Load + compile heuristic regexes from ``app/data/patterns.yaml`` (cached)."""
    try:
        with _PATTERNS_PATH.open(encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return ()
    rules: list[HeuristicRule] = []
    for raw in doc.get("rules", []) or []:
        rid = raw.get("id")
        pat = raw.get("pattern")
        if not rid or not pat:
            continue
        try:
            compiled = re.compile(pat, re.IGNORECASE)
        except re.error:
            continue
        rules.append(
            HeuristicRule(
                id=str(rid),
                pattern=compiled,
                weight=float(raw.get("weight", 0.3)),
                desc=str(raw.get("desc", "")),
            )
        )
    return tuple(rules)


def _strip_and_count(text: str) -> tuple[str, dict[str, int]]:
    """NFKC-normalize, then strip invisible/bidi/disallowed-control chars, counting what we removed."""
    normalized = unicodedata.normalize("NFKC", text)
    summary: dict[str, int] = {}
    kept: list[str] = []
    for ch in normalized:
        if ch in _INVISIBLE:
            summary["invisible"] = summary.get("invisible", 0) + 1
            continue
        if ch in _BIDI:
            summary["bidi"] = summary.get("bidi", 0) + 1
            continue
        if ch in _ALLOWED_CONTROL:
            kept.append(ch)
            continue
        cat = unicodedata.category(ch)
        # Cc = C0/C1 controls, Cf = format chars (any remaining after explicit lists above).
        if cat in ("Cc", "Cf"):
            summary["control"] = summary.get("control", 0) + 1
            continue
        kept.append(ch)
    return "".join(kept), summary


def _collapse_whitespace(text: str) -> str:
    """Collapse runs of horizontal whitespace to a single space; cap blank-line runs; trim."""
    collapsed = _WS_RUN_RE.sub(" ", text)
    collapsed = _NEWLINE_RUN_RE.sub("\n\n", collapsed)
    # Trim trailing spaces on each line + overall.
    collapsed = "\n".join(line.strip() for line in collapsed.split("\n"))
    return collapsed.strip()


def _detect_homoglyph_mixing(text: str) -> bool:
    """Flag tokens that mix Latin with Cyrillic/Greek letters (e.g. 'pаypal' with a Cyrillic 'а')."""
    for token in _TOKEN_RE.findall(text):
        if len(token) < 2:
            continue
        has_latin = bool(_LATIN_RE.search(token))
        has_confusable = bool(_CYRILLIC_RE.search(token) or _GREEK_RE.search(token))
        if has_latin and has_confusable:
            return True
    return False


def _scan_heuristics(text: str) -> tuple[float, list[str]]:
    """Run advisory regexes; accumulate suspicion (clamped to 1.0) + the ordered hit ids."""
    score = 0.0
    hits: list[str] = []
    for rule in _load_rules():
        if rule.pattern.search(text):
            hits.append(rule.id)
            score += rule.weight
    return min(score, 1.0), hits


def preprocess(raw_prompt: str) -> PreprocessResult:
    """Run Layer 1 on untrusted text. Deterministic and total (never raises on input)."""
    text = raw_prompt or ""
    clean, removed = _strip_and_count(text)
    clean = _collapse_whitespace(clean)

    homoglyph = _detect_homoglyph_mixing(clean)
    score, hits = _scan_heuristics(clean)
    if homoglyph:
        # Homoglyph mixing is a soft signal — add to suspicion, never block.
        score = min(score + 0.2, 1.0)
        if removed.get("invisible") or removed.get("bidi"):
            score = min(score + 0.1, 1.0)

    return PreprocessResult(
        clean_text=clean,
        removed_char_summary=removed,
        suspicion_score=round(score, 3),
        heuristic_hit_ids=hits,
        homoglyph_mixing=homoglyph,
    )
