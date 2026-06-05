# SchoolAutomaton — Frozen Architecture Spec (v1)

> Canonical, build-ready reference. Full design detail: [docs/architecture-design.json](docs/architecture-design.json).
> Research dossiers digest: [docs/research/research-digest.json](docs/research/research-digest.json).
> **This document + the contract files it points to are the single source of truth. Implementation
> modules must import the frozen contracts and must NOT modify them.**

## 1. What it is

A student types one free-text prompt (e.g. *"I want to learn about photosynthesis at 5th grade level"*).
SchoolAutomaton **sanitizes** the prompt (hardened against prompt injection / off-task / unsafe input),
**extracts a structured intent**, then generates **either** rich visual **study materials** **or** an
interactive, playful, gamified **test** — with gamification (XP, streaks, mastery-anchored badges,
knowledge tree) and evidence-based pedagogy (retrieval practice, FSRS-6 spaced repetition, dual coding,
Bloom's taxonomy, worked examples, growth-mindset feedback) baked in throughout.

No student registration: **anonymous server profiles** with a short **resume code**. Admin behind login.
**Multilingual** (auto-detected from the prompt). **Mobile-first**, light, playful, simple UI.

## 2. Stack (frozen)

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 async + aiosqlite (SQLite, WAL), Pydantic v2, Alembic,
  `anthropic` (AsyncAnthropic, Claude **Opus 4.8** = `claude-opus-4-8`; sanitizer screen on **Haiku 4.5** =
  `claude-haiku-4-5`), `replicate`, `fsrs>=6.3.1`, `textstat`, `argon2-cffi`, `python-jose` (JWT),
  `cryptography` (Fernet), `lxml` (SVG sanitize), `slowapi`/custom rate limiter, `PyYAML`.
- **Frontend:** Vue 3.5, Vite 7, TypeScript 5.6, Tailwind 4 (CSS-first `@theme`, no config file), Pinia 3
  (+persistedstate), vue-router 4, `@vueuse/core` + `@vueuse/motion`, `gsap`, `@lottiefiles/dotlottie-vue`,
  `markdown-it` + KaTeX, `dompurify`, `vuedraggable@4`, `vue-i18n@10`, Lexend / Atkinson Hyperlegible /
  OpenDyslexic fonts. **openapi-typescript** generates `src/types/api.ts` from FastAPI's OpenAPI.
- **Deploy:** Docker Compose (backend + frontend served by nginx, shared named volume for SQLite + asset
  cache). Update/deploy scripts for Windows (PowerShell) and Linux (bash).

## 3. Core flow (one-way data flow — the central safety invariant)

```
raw prompt (untrusted)
  → Layer 0 rate-limit  → Layer 1 deterministic preprocess  → Layer 2 Haiku classifier (structured)
  → Layer 3 deterministic validate  → Decision { proceed | clarify | refuse | crisis }
  → [proceed] Generation orchestrator (Opus 4.8) — builds prompts ONLY from validated StructuredIntent,
              NEVER from raw text → Lesson (12-section skeleton) OR Quiz (typed questions)
  → persist to SQLite + content-hashed visual assets on disk → SSE progress
  → Frontend LessonReader / TestRunner → answers POSTed → deterministic/LLM grading
  → FSRS update + mastery + XP + badges + streak → Results
```

**INVARIANT (unit-tested):** no `raw_prompt` value ever reaches any generator/visual function. Generators
consume only the frozen `StructuredIntent`. See `tests/test_no_raw_leak.py`.

## 4. Resolved open decisions (locked for v1)

| # | Decision | Resolution |
|---|----------|------------|
| 1 | Resume code | 8-char Crockford base32, dash-grouped (`K7QF-2M9X`). Shown once on create; re-showable on demand in Settings. QR/deeplink = post-v1. No passphrase (keep frictionless). Server stores only `resume_code_hash` (sha256); raw code shown to client once and cached in localStorage. |
| 2 | Real-time transport | **SSE** (`GET /requests/{id}/stream`) for generation progress. Poll fallback endpoint provided. No WebSockets in v1. |
| 3 | Background tasks | **In-process** `asyncio` task registry + FastAPI `BackgroundTasks` (SQLite single-writer + Compose favors in-process). A small `app/core/tasks.py` registry tracks status for SSE. No external broker in v1. |
| 4 | Replicate | **100% hosted** (pay-per-use, license-safe for flux-2-dev non-commercial weights). No self-hosting in v1. |
| 5 | Mastery formula | `mastery = clamp01( Σ wₛ·R(t,S) / Σ wₛ )` over a concept's items, weights `w`: Review=1.0, Relearning=0.7, Learning=0.5, New=0.0. New-only concept ⇒ mastery 0. `mastered` ≥ 0.85; `needs_review` when `now > decay_due_at`. Frozen in `app/services/mastery.py` + fixture `tests/test_mastery.py`. |
| 6 | FSRS rating derivation | Deterministic, server-side, single mapping used by `/answers` and `/review`: `Again(1)`=incorrect; `Hard(2)`=correct AND (used_hint OR latency>slow_threshold); `Good(3)`=correct, no hint, normal; `Easy(4)`=correct, no hint, latency<quick_threshold. Thresholds: per-item-type static config in `app/core/constants.py` (`LATENCY_THRESHOLDS`). |
| 7 | Concept graph | Grown **lazily** by the generator (`INSERT OR IGNORE` on slug); LLM proposes prerequisite/related edges; admin can view/curate. No hand-seeded ontology in v1 beyond a tiny bootstrap. |
| 8 | Crisis resources | `app/data/crisis_resources.yaml` with per-country + global fallback (US 988, UK Samaritans 116 123, EU 112, Befrienders Worldwide link). Non-dismissable crisis card + AI-disclosure copy. **Carries a "legal review pending" note** in admin docs. |
| 9 | i18n scope | UI ships **`en` + `cs`** (Czech) at launch; generation auto-detects ANY language. A **single English** pedagogy cached prefix serves all languages; the output language is pinned by a "respond entirely in {language}" directive in the trailing user message (no per-language prompt copies to keep in sync). |
| 10 | Daily caps / retention | New-item daily cap: 20 (early_primary 10). `desired_retention` default 0.90 (0.85 casual / 0.95 deadline) — exposed as an *advanced* profile setting, not prominent. |
| 11 | Leaderboards | **OFF** by default. `competitive_opt_in` flag + personal-best framing exist; ability-banded leagues NOT shipped in v1. |
| 12 | Batches pre-gen | Mechanism provided as an **admin-triggered** action + script; no automatic nightly cron in v1. |

## 5. Conventions (all code)

- **Async everywhere** (SQLAlchemy async session, AsyncAnthropic, async replicate, async routes).
- **Config constants** centralized in `app/core/config.py` (env-driven `Settings`) and `app/core/constants.py`
  (pedagogy/gamification/visual constants). `MODEL_ID`, `SANITIZER_MODEL_ID`, `PROMPT_VERSION` are stamped on
  every generated row.
- **Structured LLM output** via `client.messages.parse(output_format=PydanticModel)`. **Never** assistant
  prefill, **never** send `temperature`/`top_p`/`top_k`/`budget_tokens` (400 on Opus 4.8). `thinking={"type":
  "adaptive"}` always on. Always check `stop_reason` before trusting parsed output. JSON-schema `minimum/maximum/
  minLength/maxLength` are stripped by 4.8 → enforce bounds in prompt text **and** Pydantic validators;
  regenerate (max 2 retries) on validation failure. `additionalProperties:false` on every object.
- **Prompt caching:** each content family has a byte-identical `cache_control:{type:'ephemeral'}` system prefix
  (no `datetime.now`, no uuid, no unsorted json). Volatile data (date, profile id, language, mastery, topic)
  goes only in the trailing user message. Verify `usage.cache_read_input_tokens>0`; log to `generation_usage`.
- **All LLM/Replicate output is untrusted** → server sanitizes SVG (lxml) on store; client DOMPurifies markdown
  + SVG on render; strict CSP. Answers/explanations are **server-only** at delivery, revealed only by the
  grading endpoint.
- **Naming:** Python `snake_case`, modules lowercase. Vue components `PascalCase.vue`, composables `useX.ts`,
  Pinia stores `useXStore`. JSON API keys English; all student-facing *values* localized.
- API base path: `/api/v1`. Auth headers: learner `X-Resume-Code`; admin `Authorization: Bearer <jwt>`.

## 6. Module ownership map (anti-drift partition)

The **spine** (written first, frozen): `app/core/*`, `app/db/*`, `app/models/*`, `app/schemas/*`,
all `app/api/v1/routes/*` handlers (they define the API contract and call services by frozen signature),
`app/main.py`; frontend `package.json`, `vite.config.ts`, `src/main.ts`, `src/style/*`, `src/types/*`,
`src/router/*`, `src/stores/*` (interfaces), `src/lib/api.ts`. Spine files are **read-only** to module agents.

Module bodies (filled by implementation agents, each owns DISJOINT files):

| Module | Files | Frozen interface it implements |
|--------|-------|-------------------------------|
| **B1 Sanitization** | `app/sanitization/{preprocess,classifier,validate,safety,audit,ratelimit}.py`, `app/data/patterns.yaml`, `app/data/crisis_resources.yaml` | `sanitize_request(raw, ctx) -> Decision` |
| **B2 LLM generation** | `app/llm/{client,prompts/*,lesson_generator,quiz_generator,grader}.py` | `generate_lesson(intent, request) -> Lesson`, `generate_quiz(...)`, `grade_answer(...)` |
| **B3 Visuals** | `app/visuals/{router,claude_svg,replicate_raster,cache,svg_sanitize}.py` | `ensure_visual(spec) -> VisualAsset` |
| **B4 Pedagogy/gamification services** | `app/services/{srs_service,mastery,leveling,gamification,badges,interleave}.py`, `app/data/badges.yaml` | the service signatures documented in §7 |
| **F1 Design system / shell** | `src/components/{common,layout}/*`, `src/composables/{useReducedMotion,useCelebration}.ts`, `src/locales/*` | design tokens already in `src/style/` |
| **F2 Question components** | `src/components/questions/*`, `src/components/content/{SafeContent,LessonSection,MathBlock}.vue`, `src/lib/safeContent.ts` | `AnswerEvent` contract in `src/types/question.ts` |
| **F3 Views + flows** | `src/views/*` (non-admin), store bodies, `src/composables/{useGeneration,useApi}.ts` | store interfaces + `src/lib/api.ts` |
| **F4 Gamification UI** | `src/components/gamification/*` | gamification API responses |
| **F5 Admin** | `src/views/admin/*` | admin API |

## 7. Service interface contract (B4 — frozen signatures)

```python
# app/services/srs_service.py
def new_card() -> dict                                   # py-fsrs Card.to_json()
def review(card_json: str, rating: int, now: datetime) -> tuple[dict, datetime]   # -> (new card_json, due)
def derive_rating(is_correct: bool, used_hint: bool, latency_ms: int|None, item_type: str) -> int

# app/services/mastery.py
def concept_mastery(cards: list[FsrsCardRow], now: datetime) -> float             # see decision #5
def node_state(mastery: float, prereqs_met: bool, decay_due_at: datetime|None, now: datetime) -> str

# app/services/leveling.py  (pure)
def xp_total_for_level(level: int) -> int          # round(100 * level**1.5)
def level_from_xp(total_xp: int) -> int
def xp_to_next(total_xp: int) -> int
def level_progress_pct(total_xp: int) -> float
def item_xp(item_difficulty: int, mastery_before: float, *, base: int = BASE_ITEM_XP) -> int  # round(base*diff/3*(1-mastery))
def combo_multiplier(consecutive_first_try: int) -> float   # pure/sync; 1.0 → 2.0 cap at 8

# app/services/gamification.py  (async, DB-touching)
async def grade_and_reward(db, profile, item, answer, attempt_id) -> GradeResult   # orchestrates srs+mastery+xp+badges+streak
async def finalize_attempt(db, profile, attempt_id) -> ResultsSummary              # end-of-quiz score/accuracy/mastery-delta
async def settle_streak(db, profile, now) -> StreakInfo                            # silent freeze/rest-day/repair forgiveness

# app/services/badges.py
async def evaluate_badges(db, profile, event) -> list[BadgeAward]
```

## 8. Build order

1. **Spine** (this freeze + scaffold): contracts, models, schemas, config, routes calling service stubs,
   frontend shell + types + tokens, Docker, env. *(Claude main, sequential.)*
2. **Module bodies** in parallel against the spine. *(Agents.)*
3. **Adversarial review + integration**, then run end-to-end (backend pytest + uvicorn, frontend vite build),
   fix until green. *(Workflow + Claude main.)*

## 9. Key risks to actively guard (from design)

Prompt-injection→child-safety breakout (one-way flow + deterministic validate + red-team corpus in CI);
XSS via LLM/SVG output (dual sanitize + CSP); cost blow-up (verify cache hits, pin megapixels=1, asset cache);
prompt-cache silent misses (assert byte-identical prefix in tests); FSRS/mastery drift (lock formula + fixture);
SQLite write contention (WAL + INSERT OR IGNORE + funnel writes).
