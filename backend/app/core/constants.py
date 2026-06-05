"""Frozen pedagogy / gamification / visual constants and lookup tables.

Numeric knobs and mappings live here (env-overridable ones live in ``config.py``). Changing values
that feed FSRS/mastery/XP is a contract change — update the matching unit-test fixtures too
(``tests/test_mastery.py``, ``tests/test_leveling.py``). See SPEC §4 (#5, #6) and §7.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Versioning — stamped on every generated row for audit + cache-busting.
# Bump PROMPT_VERSION whenever a cached system prefix or generation prompt changes.
# ---------------------------------------------------------------------------
PROMPT_VERSION = "2026.06.05"

# ---------------------------------------------------------------------------
# Readability targets per grade band: (target_FKGL, lexile_band, max_words_per_sentence, max_new_terms)
# FKGL is English-only; non-English content uses a proxy + a readability_note (see B2).
# Regenerate (max 2x) if measured FKGL > target + READABILITY_TOLERANCE.
# ---------------------------------------------------------------------------
READABILITY_TOLERANCE = 1.5

READABILITY_TARGETS: dict[str, dict] = {
    "K":     {"fkgl": 1.0,  "lexile": "BR40L-230L",  "max_sentence_words": 8,  "max_new_terms": 3},
    "G1-2":  {"fkgl": 2.0,  "lexile": "190L-650L",   "max_sentence_words": 10, "max_new_terms": 3},
    "G3-5":  {"fkgl": 4.0,  "lexile": "520L-1010L",  "max_sentence_words": 15, "max_new_terms": 5},
    "G6-8":  {"fkgl": 7.0,  "lexile": "925L-1185L",  "max_sentence_words": 20, "max_new_terms": 8},
    "G9-12": {"fkgl": 10.0, "lexile": "1050L-1385L", "max_sentence_words": 24, "max_new_terms": 12},
    "adult": {"fkgl": 10.0, "lexile": "1100L-1300L", "max_sentence_words": 26, "max_new_terms": 15},
    "unknown": {"fkgl": 7.0, "lexile": "925L-1185L", "max_sentence_words": 20, "max_new_terms": 8},
}

# Bloom tiers (1..6) emphasized per grade band — used to weight item generation.
BLOOM_EMPHASIS: dict[str, tuple[int, ...]] = {
    "K":     (1, 2),
    "G1-2":  (1, 2, 3),
    "G3-5":  (1, 2, 3),
    "G6-8":  (1, 2, 3, 4),
    "G9-12": (2, 3, 4, 5, 6),
    "adult": (2, 3, 4, 5, 6),
    "unknown": (1, 2, 3, 4),
}

# ---------------------------------------------------------------------------
# Adaptive difficulty / FSRS rating derivation.
# Target success rate (ZPD) fed into quiz generation.
# ---------------------------------------------------------------------------
TARGET_SUCCESS_RATE = 0.83          # 0.80-0.85 band
ADAPT_STEP_UP_AFTER = 2             # +1 difficulty after N consecutive correct
ROLLING_ACCURACY_WINDOW = 10

# Per item-type latency thresholds (ms) for Hard/Easy rating derivation (SPEC §4 #6).
# (quick_ms below => Easy candidate; slow_ms above => Hard). Static for v1.
LATENCY_THRESHOLDS: dict[str, dict[str, int]] = {
    "mcq":          {"quick": 4_000,  "slow": 25_000},
    "true_false":   {"quick": 2_500,  "slow": 15_000},
    "cloze":        {"quick": 5_000,  "slow": 35_000},
    "short_answer": {"quick": 12_000, "slow": 90_000},
    "numeric":      {"quick": 6_000,  "slow": 45_000},
    "match":        {"quick": 8_000,  "slow": 50_000},
    "order":        {"quick": 8_000,  "slow": 50_000},
    "hotspot":      {"quick": 4_000,  "slow": 25_000},
}
DEFAULT_LATENCY_THRESHOLD = {"quick": 5_000, "slow": 30_000}

# ---------------------------------------------------------------------------
# Spaced repetition (FSRS) + mastery (SPEC §4 #5).
# ---------------------------------------------------------------------------
DESIRED_RETENTION_DEFAULT = 0.90
DESIRED_RETENTION_CASUAL = 0.85
DESIRED_RETENTION_DEADLINE = 0.95
FSRS_LEARNING_STEPS_MIN = (1, 10)       # minutes
FSRS_RELEARNING_STEPS_MIN = (10,)       # minutes
FSRS_MAXIMUM_INTERVAL_DAYS = 36500
FSRS_ENABLE_FUZZING = True

# Daily new-item caps per age band (all overdue items are always surfaced on top of this).
DAILY_NEW_CAP: dict[str, int] = {
    "early_primary": 10,
    "primary": 20,
    "lower_secondary": 20,
    "upper_secondary": 25,
    "adult": 30,
    "unknown": 20,
}

# Mastery aggregation weights by FSRS card state (0=New,1=Learning,2=Review,3=Relearning).
MASTERY_STATE_WEIGHTS: dict[int, float] = {0: 0.0, 1: 0.5, 2: 1.0, 3: 0.7}
MASTERY_MASTERED_THRESHOLD = 0.85

# Interleaved review composition (must sum to ~1.0).
INTERLEAVE_COMPOSITION = {"current": 0.55, "related": 0.25, "prereq": 0.20}
INTERLEAVE_STRENGTH_DEFAULT = 0.30
INTERLEAVE_STRENGTH_EARLY_PRIMARY = 0.10

# ---------------------------------------------------------------------------
# Gamification — XP curve + per-answer XP (SPEC gamification design).
# ---------------------------------------------------------------------------
BASE_XP = 100            # xp_total(L) = round(BASE_XP * L**CURVE_EXP)
CURVE_EXP = 1.5
BASE_ITEM_XP = 10        # item_xp = round(BASE_ITEM_XP * (item_difficulty/3) * (1 - mastery_before))
COMBO_CAP = 2.0          # max session multiplier
COMBO_FULL_AT = 8        # combo reaches COMBO_CAP at this consecutive-correct count

# Streaks.
STREAK_FREEZE_CAP_DEFAULT = 2
STREAK_FREEZE_CAP_LONG = 5            # for streaks >= 30 days
STREAK_LONG_THRESHOLD_DAYS = 30
STREAK_REPAIR_WINDOW_HOURS = 48
REST_DAYS_PER_WEEK_DEFAULT = 0
REST_DAYS_PER_WEEK_YOUNG = 1         # early_primary / under-13

# Daily-goal presets -> target XP.
DAILY_GOAL_XP = {"casual": 50, "regular": 100, "serious": 150, "intense": 200}

# ---------------------------------------------------------------------------
# Visual pipeline (SPEC visual_pipeline). Model ids are config-overridable; these are the defaults.
# ---------------------------------------------------------------------------
SVG_VISUAL_KINDS = frozenset({
    "diagram", "chart", "labeled_figure", "cycle", "timeline",
    "geometry", "number_line", "food_chain", "map",
})
RASTER_VISUAL_KINDS = frozenset({"illustration", "scene", "character", "photo"})
SVG_MAX_BYTES = 60_000

# layout_slot -> (aspect_ratio, megapixels, model_tier, tailwind_aspect_class)
LAYOUT_SLOT_SPECS: dict[str, dict] = {
    "HERO":               {"aspect": "16:9", "megapixels": 1.0,  "tier": "default", "tw": "aspect-video"},
    "INLINE_FIGURE":      {"aspect": "4:3",  "megapixels": 1.0,  "tier": "default", "tw": "aspect-[4/3]"},
    "QUIZ_THUMB":         {"aspect": "1:1",  "megapixels": 0.25, "tier": "cheap",   "tw": "aspect-square"},
    "PORTRAIT_CHARACTER": {"aspect": "3:4",  "megapixels": 1.0,  "tier": "hero",    "tw": "aspect-[3/4]"},
    "FULL_BLEED_MOBILE":  {"aspect": "9:16", "megapixels": 1.0,  "tier": "default", "tw": "aspect-[9/16]"},
}

# Replicate model tiers (config can override via app_settings / env).
REPLICATE_MODELS_DEFAULT = {
    "default": "black-forest-labs/flux-2-dev",
    "cheap": "black-forest-labs/flux-2-klein-4b",
    "hero": "black-forest-labs/flux-2-pro",
    "typography": "black-forest-labs/flux-2-flex",
    "video": "wan-video/wan-2.2-i2v-fast",
}

# Kid-safe Replicate prompt scaffold. {subject} and {grade} are filled from validated intent ONLY.
REPLICATE_PROMPT_TEMPLATE = (
    "A friendly, colorful flat vector illustration of {subject}, simple clean shapes, soft rounded "
    "edges, bright cheerful palette, plain off-white background, no text, no labels, educational "
    "children's textbook style, age-appropriate for {grade}, safe for kids, clear and uncluttered, "
    "centered composition."
)
REPLICATE_NEGATIVE_CLAUSE = (
    "Do not include: scary imagery, violence, blood, weapons, realistic human faces, brand logos, "
    "watermarks, or any written text."
)

# ---------------------------------------------------------------------------
# i18n — UI locales shipped at launch. Generation auto-detects any language.
# Native pedagogy cached prefixes are built for these; others fall back to English + "respond in X".
# ---------------------------------------------------------------------------
SHIPPED_UI_LOCALES = ("en", "cs")
NATIVE_PEDAGOGY_LANGUAGES = ("en", "cs")
DEFAULT_LOCALE = "en"

# Mastery-anchored badge codes (definitions seeded from app/data/badges.yaml).
BADGE_CODES = (
    "first_light", "root_system", "deep_diver", "comeback", "spaced_master",
    "sharpshooter", "honest_explorer", "polyglot", "cross_pollinator", "curiosity",
    "self_beater", "tree_grower", "teacher", "resilient", "marathon_of_mastery",
)
