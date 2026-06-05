# CLAUDE.md — SchoolAutomaton

Self-learning web tool. Student types one prompt → sanitized & intent-extracted → generates **study
materials** or an interactive **test**, with gamification + evidence-based pedagogy. Multilingual,
mobile-first, anonymous (resume code), admin behind login.

**Read [SPEC.md](SPEC.md) first** — it is the frozen architecture + the conventions every change must follow.
Full design detail in [docs/architecture-design.json](docs/architecture-design.json).

## Layout
```
backend/    FastAPI app (app/core, app/db, app/models, app/schemas, app/api, app/sanitization,
            app/llm, app/visuals, app/services, app/data); tests/; alembic/
frontend/   Vue 3 + Vite + TS SPA (src/{views,components,stores,composables,lib,types,style,locales})
infra/      Docker Compose, Dockerfiles, nginx, deploy/update scripts
docs/       architecture-design.json, research digest
data/        (gitignored) SQLite db + content-hashed visual cache  (Docker named volume in prod)
```

## Run (dev)
- Backend: `cd backend && python -m venv .venv && .venv/Scripts/activate && pip install -r requirements.txt && uvicorn app.main:app --reload`
- Frontend: `cd frontend && npm install && npm run dev`
- Full stack: `docker compose up --build` (see `infra/`). Deploy/update: `infra/scripts/*`.
- Env: copy `.env.example` → `.env`, set `ANTHROPIC_API_KEY`, `REPLICATE_API_TOKEN`, `APP_SECRET`, `ADMIN_*`.

## Non-negotiable invariants
1. **One-way flow:** raw student text is untrusted; generators/visuals receive only the validated
   `StructuredIntent` — never raw text. (`tests/test_no_raw_leak.py`.)
2. **All LLM/Replicate output is untrusted:** server sanitizes SVG (lxml); client DOMPurifies markdown+SVG;
   strict CSP. Quiz answers/explanations are server-only until the grading endpoint reveals them.
3. **FSRS-6 (`py-fsrs`) is the only scheduler;** mastery is *derived* from FSRS retrievability (no second
   algorithm). Never hand-code FSRS math. Mastery formula + rating derivation are frozen (SPEC §4 #5/#6).
4. **Prompt caching must stay byte-identical** (no datetime/uuid/unsorted-json in cached prefixes); tests
   assert `cache_read_input_tokens>0`.
5. Claude Opus 4.8: no prefill, no temperature/top_p/top_k, `thinking=adaptive` on, enforce numeric bounds in
   prompt + Pydantic (schema bounds are stripped). Stamp `MODEL_ID`/`PROMPT_VERSION` on generated rows.
6. **Mobile-first** Tailwind (base styles for phones, layer `sm:`/`md:`/`lg:` up). WCAG 2.2 AA, ≥44px targets,
   never color-only meaning, reduced-motion honored.

## Anti-drift seams
Shared Pydantic schemas in `backend/app/schemas/` are imported by sanitizer + generator. FastAPI OpenAPI →
`frontend/src/types/api.ts` via `openapi-typescript` (`npm run gen:api`). Service signatures frozen in SPEC §7.
