"""Czech RVP ZV expected learning outcomes: pick the ones a lesson or quiz serves, for the volatile tail.

The catalogue in ``app/data/rvp_zv.json`` is NPI's open data (``scripts/import_rvp_zv.py``): every
expected learning outcome of the basic-school curriculum, with its code, subject, strand, stage (ZV5 =
the target at the end of grade 5, ZV9 = at the end of grade 9) and descriptions of three phases of
mastering it ("Na začátku" / "Na cestě" / "Splněno").

Selection is deterministic and runs only for the Czech education system (``cs-CZ``) at basic-school
level (school years 1-9, or the G1-2 … G6-8 bands when no exact year is known):

1. the learner's subject and stage give the candidate outcomes (``SUBJECT_SCOPE``);
2. the topic is matched against each candidate's statement, strand and phase descriptions (light Czech
   stemming, weighted by how rare a word is across the stage), keeping at most ``MAX_MATCHES``;
3. matches are shown in full, with the phase that fits the learner's grade and the end-of-stage target;
   without a confident match the steps that set the objectives (lesson plan, quiz) get the subject's
   whole outcome list (statements only) and pick, while section calls get nothing extra.

The phase guides the pitch only: the directive always tells the model to cover the requested topic
completely, as taught in the learner's grade.

The directive goes ONLY in the trailing user message — never the cached system prefix (SPEC §5 #4).
The topic is the validated ``StructuredIntent.topic``, never raw student text (SPEC §3).
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path

from ...schemas.enums import Subject

_RVP_JSON = Path(__file__).resolve().parents[2] / "data" / "rvp_zv.json"

LOCALE = "cs-CZ"
MAX_MATCHES = 3
MAX_LISTED = 50       # cap on the statements-only list shown when nothing matched
_PHASE_CHARS = 420    # a phase description is cut (at a word) to keep the tail short


def _load() -> dict:
    if not _RVP_JSON.is_file():  # pragma: no cover - defensive; the file ships with the app
        return {}
    data = json.loads(_RVP_JSON.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


# Loaded once at import (deterministic; only ever read).
RVP_ZV: dict = _load()
OUTCOMES: dict[str, dict] = {o["code"]: o for o in RVP_ZV.get("outcomes", [])}
SUBJECTS: dict[str, dict] = RVP_ZV.get("subjects", {})

# App subject -> stage -> outcome-code prefixes ("area-subject" or "area-subject-strand"). At the 1st
# stage most subjects are one integrated subject, Člověk a jeho svět (CJS), so they narrow to its strand.
SUBJECT_SCOPE: dict[Subject, dict[str, tuple[str, ...]]] = {
    Subject.MATH: {"ZV5": ("MAT-MAT",), "ZV9": ("MAT-MAT",)},
    Subject.LANGUAGE_ARTS: {"ZV5": ("JJK-CJL",), "ZV9": ("JJK-CJL",)},
    Subject.FOREIGN_LANGUAGE: {"ZV5": ("JJK-AJA",), "ZV9": ("JJK-AJA", "JJK-DCJ")},
    Subject.COMPUTER_SCIENCE: {"ZV5": ("INF-INF",), "ZV9": ("INF-INF",)},
    Subject.SCIENCE: {"ZV5": ("CJS-CJS-004", "CJS-CJS-005"), "ZV9": ("CAP-FYZ", "CAP-CHE", "CAP-PRI")},
    Subject.BIOLOGY: {"ZV5": ("CJS-CJS-004", "CJS-CJS-005"), "ZV9": ("CAP-PRI",)},
    Subject.CHEMISTRY: {"ZV5": ("CJS-CJS-004",), "ZV9": ("CAP-CHE",)},
    Subject.PHYSICS: {"ZV5": ("CJS-CJS-004",), "ZV9": ("CAP-FYZ",)},
    Subject.GEOGRAPHY: {"ZV5": ("CJS-CJS-001",), "ZV9": ("GEO-GEO",)},
    Subject.HISTORY: {"ZV5": ("CJS-CJS-003",), "ZV9": ("CAS-DEJ",)},
    Subject.SOCIAL_STUDIES: {"ZV5": ("CJS-CJS-001", "CJS-CJS-002"), "ZV9": ("CAS-VKO",)},
    Subject.ECONOMICS: {"ZV5": ("CJS-CJS-006",), "ZV9": ("CAS-VKO-003",)},
    Subject.HEALTH: {"ZV5": ("CJS-CJS-005",), "ZV9": ("CZB-VZB",)},
    Subject.ARTS: {"ZV5": ("UAK-VFV",), "ZV9": ("UAK-VFV",)},
    Subject.MUSIC: {"ZV5": ("UAK-HTD",), "ZV9": ("UAK-HTD",)},
}

_STAGE_BY_BAND = {"G1-2": "ZV5", "G3-5": "ZV5", "G6-8": "ZV9"}
_STAGE_GRADE = {"ZV5": 5, "ZV9": 9}
# Where a learner in a given grade typically is on the way to the end-of-stage target. A guide for the
# pitch (the RVP sets targets per stage, not per grade), so the model is told it is "typically".
_PHASE_BY_YEAR = {1: "start", 2: "start", 3: "on_the_way", 4: "on_the_way", 5: "met",
                  6: "start", 7: "on_the_way", 8: "on_the_way", 9: "met"}
_PHASE_BY_BAND = {"G1-2": "start", "G3-5": "on_the_way", "G6-8": "on_the_way"}
_PHASE_LABEL = {"start": "Na začátku", "on_the_way": "Na cestě", "met": "Splněno"}


@dataclass(frozen=True)
class RvpSelection:
    stage: str                      # "ZV5" | "ZV9"
    phase: str                      # "start" | "on_the_way" | "met"
    matched: tuple[dict, ...]       # outcomes the topic matched, best first (may be empty)
    candidates: tuple[dict, ...]    # every outcome in the subject's scope at this stage, by code


# --------------------------------------------------------------------------- topic matching
# Czech + English function words and words that say nothing about the topic. Compared after
# lowercasing and stripping diacritics. (Word lists read better as one string than as literals.)
_STOPWORDS = frozenset(
    """a aby ale ani anebo ano asi az bez bude budou by byl byla byli bylo byt co coz do dal ho i
    jak jake jaky jako je jeho jej jeji jejich jen jeste ji jsem jsi jsme jsou jste k kam kde kdo
    kdy kdyz ke ktera ktere kteri ktery ma maji mam me mezi mi mit mne mu muj my na nad nam nas
    nebo nejak neni nez ni nic o od ode po pod podle pokud pro proc proto protoze pred pres pri
    s se si sve svuj ta tak take tam te tedy ten teto tim tito to tu ty u uz v ve vsak z za ze
    lekce lekci test testu kviz ucivo uceni ucit naucit tema tematu trida tridu tridy rocnik
    rocniku zakladni skola skoly zs priprava procvicovani opakovani prijimacky
    the and for with about from into what how why lesson quiz test grade class learn learning""".split()  # noqa: SIM905
)
# Case endings; the longest one that leaves at least three letters is dropped.
_SUFFIX_WORDS = """atech etem atum ech ich eho emi emu ete eti iho imi imu ach ata aty ych ama ami ove ovi
    ymi em es im um at am os us ym mi ou e i a o u y""".split()  # noqa: SIM905
_SUFFIXES_BY_LEN = tuple((n, frozenset(w for w in _SUFFIX_WORDS if len(w) == n)) for n in range(5, 0, -1))
_STEM_LEN = 5


def _fold(text: str) -> str:
    """Lowercase ASCII without diacritics ('Násobilka' -> 'nasobilka'); other non-ASCII is dropped,
    which is fine because only [a-z0-9] runs become words."""
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")


@cache
def _stem(word: str) -> str:
    """A light Czech stem: drop one case ending, then keep the first five letters, so 'zlomky',
    'zlomku' and 'zlomků' all become 'zlomk' and 'násobilka'/'násobení' become 'nasob'."""
    for n, suffixes in _SUFFIXES_BY_LEN:
        if len(word) - n >= 3 and word[-n:] in suffixes:
            word = word[:-n]
            break
    return word[:_STEM_LEN]


def _stems(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", _fold(text))
    return {_stem(w) for w in words if len(w) >= 3 and w not in _STOPWORDS}


# Field weights: the statement says what the outcome is; the strand names its area; the phase
# descriptions carry the concrete vocabulary (zlomky, teploměr, obvod …) but also a lot of noise.
_FIELD_WEIGHTS = (("text", 3.0), ("strand", 2.0), ("phases", 1.0))
# A match must be worth at least this much: about one rare word in the statement, or two rare words
# in the phase descriptions — a single common word ('slova', 'úlohy') is not enough.
MIN_SCORE = 6.0


@dataclass(frozen=True)
class _FieldIndex:
    """One field's stems as lookups. Two stems match when equal, or when one of at least four letters
    starts the other ('slov' / 'slovn'); stems are at most five letters, so that is: equal, a 4-letter
    topic stem starting a field stem (``by_prefix``), or a 4-letter field stem starting a 5-letter
    topic stem (``four``). Each maps to the best idf among the matching field stems."""

    exact: dict[str, float]
    by_prefix: dict[str, float]
    four: dict[str, float]

    @classmethod
    def build(cls, stems: set[str], idf: dict[str, float]) -> _FieldIndex:
        exact = {s: idf[s] for s in stems}
        by_prefix: dict[str, float] = {}
        for s in stems:
            if len(s) >= 4:
                by_prefix[s[:4]] = max(by_prefix.get(s[:4], 0.0), idf[s])
        return cls(exact, by_prefix, {s: v for s, v in exact.items() if len(s) == 4})

    def hit(self, stem: str) -> float | None:
        """The best idf of a field stem matching ``stem``, or ``None`` when none does."""
        values = [self.exact.get(stem)]
        if len(stem) == 4:
            values.append(self.by_prefix.get(stem))
        elif len(stem) == 5:
            values.append(self.four.get(stem[:4]))
        found = [v for v in values if v is not None]
        return max(found) if found else None


@lru_cache(maxsize=1)
def _index() -> dict[str, dict[str, _FieldIndex]]:
    """Per outcome and field, its stems weighted by their inverse document frequency in the stage."""
    stems: dict[str, dict[str, set[str]]] = {}
    df: dict[str, dict[str, int]] = {}
    count: dict[str, int] = {}
    for code, outcome in OUTCOMES.items():
        stems[code] = {
            "text": _stems(outcome["text"]),
            "strand": _stems(outcome["strand"]),
            "phases": _stems(" ".join(outcome.get("phases", {}).values())),
        }
        stage = outcome["stage"]
        count[stage] = count.get(stage, 0) + 1
        stage_df = df.setdefault(stage, {})
        for stem in set().union(*stems[code].values()):
            stage_df[stem] = stage_df.get(stem, 0) + 1
    idf = {stage: {s: math.log(count[stage] / n) for s, n in stage_df.items()} for stage, stage_df in df.items()}
    return {
        code: {field: _FieldIndex.build(field_stems, idf[OUTCOMES[code]["stage"]])
               for field, field_stems in by_field.items()}
        for code, by_field in stems.items()
    }


_index()  # built at import (app startup), not inside the first learner's request


def _scores(topic_stems: set[str], candidates: tuple[dict, ...]) -> list[tuple[float, str]]:
    """(score, code) per candidate, best first. A topic word earns its field weight times how rare it
    is across the whole stage (so generic curriculum words count little), times how few of THESE
    candidates it appears in (so 'čísla' in maths, which most maths outcomes mention, can't pull in
    every number outcome, while 'záporná' still points at the one about negative numbers)."""
    index = _index()
    codes = [o["code"] for o in candidates]
    # hits[code][stem] -> per field (weight, idf) of the matches
    hits = {
        code: {stem: [(weight, v) for field, weight in _FIELD_WEIGHTS
                      if (v := index[code][field].hit(stem)) is not None]
               for stem in topic_stems}
        for code in codes
    }
    spread = {stem: sum(1 for code in codes if hits[code][stem]) for stem in topic_stems}
    scored = []
    for code in codes:
        total = 0.0
        for stem, found in hits[code].items():
            if found:
                total += max(w * v for w, v in found) * (1.0 - (spread[stem] - 1) / len(codes))
        scored.append((total, code))
    return sorted(scored, key=lambda pair: (-pair[0], pair[1]))


# --------------------------------------------------------------------------- selection
def _stage_and_phase(grade_band, school_year: int | None) -> tuple[str, str] | None:
    if school_year is not None:
        if 1 <= school_year <= 5:
            return "ZV5", _PHASE_BY_YEAR[school_year]
        if 6 <= school_year <= 9:
            return "ZV9", _PHASE_BY_YEAR[school_year]
        return None  # preschool (RVP PV) or upper-secondary (RVP G / SOŠ): not in this catalogue
    band = grade_band.value if hasattr(grade_band, "value") else str(grade_band or "")
    stage = _STAGE_BY_BAND.get(band)
    return (stage, _PHASE_BY_BAND[band]) if stage else None


def select_outcomes(
    education_locale: str | None, subject, topic: str, grade_band, school_year: int | None = None
) -> RvpSelection | None:
    """The RVP ZV outcomes for this learner and topic, or ``None`` when the catalogue doesn't apply
    (another education system, a level outside basic school, or a subject with no RVP ZV scope)."""
    if education_locale != LOCALE or not OUTCOMES:
        return None
    stage_phase = _stage_and_phase(grade_band, school_year)
    if stage_phase is None:
        return None
    stage, phase = stage_phase
    try:
        prefixes = SUBJECT_SCOPE.get(Subject(subject), {}).get(stage, ())
    except ValueError:
        return None
    candidates = tuple(
        o for code, o in OUTCOMES.items()
        if o["stage"] == stage and any(code.startswith(prefix + "-") for prefix in prefixes)
    )
    if not candidates:
        return None
    scored = _scores(_stems(topic or ""), candidates)
    best = scored[0][0]
    matched = tuple(
        OUTCOMES[code] for score, code in scored[:MAX_MATCHES]
        if score >= MIN_SCORE and score >= best / 2
    )
    return RvpSelection(stage=stage, phase=phase, matched=matched, candidates=candidates)


# --------------------------------------------------------------------------- directive
def _cut(text: str, limit: int = _PHASE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + " …"


def _where(outcome: dict) -> str:
    subject = SUBJECTS.get(outcome["subject"], {}).get("name", outcome["subject"])
    return subject if outcome["strand"] == subject else f"{subject} – {outcome['strand']}"


@lru_cache(maxsize=512)
def rvp_outcomes_directive(
    education_locale: str | None, subject, topic: str, grade_band, school_year: int | None = None,
    *, list_all: bool = True,
) -> str:
    """Volatile-tail guidance naming the RVP ZV outcomes the content should serve, or ``""``.

    ``list_all=False`` drops the subject's whole outcome list (the no-match fallback, up to ~1,500
    tokens): the steps that set the objectives (lesson plan, quiz) get it, the section calls that
    work from those objectives get only confident matches. Cached: one lesson builds a dozen prompts
    from the same intent."""
    selection = select_outcomes(education_locale, subject, topic, grade_band, school_year)
    if selection is None or not (selection.matched or list_all):
        return ""
    grade = _STAGE_GRADE[selection.stage]
    target = f"the official targets for the end of grade {grade}"
    # The scope is the requested topic as Czech schools teach it in the learner's grade. An early
    # phase must not shrink it (an eval run gave "násobilka 7" for grade 2 only 7·1-7·5 when told to
    # pitch to "the start"), and an end-of-stage target must not stretch it.
    level = "school_year" if school_year is not None else "grade_band"
    scope = f"Cover the requested topic completely, as Czech schools teach it in the learner's grade ({level} above)"
    if selection.matched:
        lines = [
            f"Czech curriculum outcomes this topic serves (RVP ZV, 'očekávané výsledky učení'; {target}):",
        ]
        for outcome in selection.matched:
            phases = outcome.get("phases", {})
            lines.append(f"- {outcome['code']} ({_where(outcome)}): {outcome['text']}")
            if selection.phase != "met" and phases.get(selection.phase):
                lines.append(f"  {_PHASE_LABEL[selection.phase]}: {_cut(phases[selection.phase])}")
            if phases.get("met"):
                lines.append(f"  Splněno: {_cut(phases['met'])}")
        if selection.phase == "met":
            pitch = "This is the year these targets should be met (\"Splněno\")."
        else:
            pitch = (
                f"A learner in this grade is typically at the \"{_PHASE_LABEL[selection.phase]}\" phase: let "
                "it guide how you explain and how hard the practice is, but it never narrows the topic."
            )
        lines.append(
            "Anchor the objectives, explanations and practice in the outcome(s) above that fit the topic; "
            f"ignore any that do not. {scope}. {pitch} The codes and phase names are for you; never show "
            "them to the learner."
        )
        return "\n".join(lines)
    lines = [f"Czech curriculum outcomes for this subject (RVP ZV, 'očekávané výsledky učení'; {target}):"]
    group = None
    for outcome in selection.candidates[:MAX_LISTED]:
        if _where(outcome) != group:
            group = _where(outcome)
            lines.append(f"{group}:")
        lines.append(f"- {outcome['code']}: {outcome['text']}")
    lines.append(
        "Pick the outcome(s) this topic serves and anchor the objectives, explanations and practice in "
        f"them; if none fits, ignore this list. {scope}: these end-of-stage targets show where it leads, "
        "they never narrow or stretch it. The codes are for you; never show them to the learner."
    )
    return "\n".join(lines)
