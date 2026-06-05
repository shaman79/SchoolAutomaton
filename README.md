# 🎓 SchoolAutomaton

**Learn anything, your way.** A student types one prompt — *"I want to learn about photosynthesis at
5th grade level"* — and SchoolAutomaton turns it into either **rich, visual study materials** or an
**interactive, playful test**, with gamification and evidence-based pedagogy woven throughout.

Built to be a wise, patient professor who can explain any topic to any age, then check understanding
on demand — visually, playfully, and effectively.

---

## ✨ What it does

- **One prompt in.** The prompt is *sanitized* (hardened against prompt injection and off-task/unsafe
  input) and reduced to a structured learning intent — subject, topic, grade level, language, and
  whether the student wants to *study* or be *tested*.
- **Study materials** follow a fixed, research-backed lesson skeleton (hook → objectives → prior
  knowledge → pretest → dual-coded explanation with generated diagrams/illustrations → worked &
  faded examples → practice → interleaved review → self-explanation → misconception check → summary).
- **Tests** are interactive and touch-first: multiple choice, true/false, fill-in-the-blank,
  drag-to-match, ordering, and image hotspots — with instant, growth-mindset feedback.
- **Gamification** that rewards real learning, not clicking: XP, levels, streaks (with gentle
  forgiveness), mastery-anchored badges, and a knowledge "garden" you tend over time.
- **Spaced repetition** (FSRS-6) schedules reviews so knowledge actually sticks.
- **Multilingual** — answers in the language the student asks in.
- **Mobile-first**, light, playful, accessible (WCAG 2.2 AA, dyslexia-friendly fonts, reduced-motion).
- **No registration.** An anonymous profile with a short *resume code* follows you across devices.
- **Admin** dashboard (behind login) for usage, cost, safety audit, settings, and the content library.

## 🧱 Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2 (async) · SQLite · Pydantic v2 |
| AI | Claude **Opus 4.8** (generation) · Claude Haiku 4.5 (prompt screening) · Replicate (illustrations) |
| Pedagogy | FSRS-6 spaced repetition · textstat readability calibration |
| Frontend | Vue 3.5 · Vite · TypeScript · Tailwind 4 · Pinia · vue-i18n |
| Deploy | Docker Compose (backend + nginx-served SPA) |

See **[SPEC.md](SPEC.md)** for the full, frozen architecture and **[CLAUDE.md](CLAUDE.md)** for the
working agreement / invariants.

## 🚀 Quick start

### Docker (recommended)
```bash
cp .env.example .env          # then set ANTHROPIC_API_KEY, REPLICATE_API_TOKEN, APP_SECRET, ADMIN_*
docker compose up --build
# App:   http://localhost:8080
# Admin: http://localhost:8080/admin/login
```
Or use the scripts: `infra/scripts/deploy.ps1` (Windows) / `infra/scripts/deploy.sh` (Linux/macOS),
and `update.ps1` / `update.sh` to redeploy.

### Local dev
```bash
# Backend
cd backend && python -m venv .venv && .venv/Scripts/activate   # (Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
uvicorn app.main:app --reload                                  # http://localhost:8000  (/docs)

# Frontend (separate terminal)
cd frontend && npm install && npm run dev                      # http://localhost:5173
```
On Windows you can launch both at once with `infra/scripts/dev.ps1`.

After the backend is running, regenerate the typed API client for the frontend with
`cd frontend && npm run gen:api`.

## 🔑 Configuration

Copy `.env.example` → `.env`. Key variables:

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude (lesson/quiz generation + prompt screening) |
| `REPLICATE_API_TOKEN` | Illustration generation |
| `APP_SECRET` | Derives the JWT signing key + the Fernet key for secrets at rest |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Bootstrap admin (created on first boot) |
| `SA_RAW_CAPTURE_ON_FLAG` | If true, retain encrypted raw text for *safety-flagged* events only |

Without API keys the app runs, profiles/gamification/admin work, and generation endpoints return a
clear "not configured" error.

## 🔒 Safety & privacy

- **One-way data flow:** the raw student prompt is treated as untrusted and is *never* passed to the
  content generators — only a validated, structured intent is. Injection attempts are stripped/flagged.
- **All AI output is sanitized** (server-side SVG hardening + client-side DOMPurify) under a strict CSP.
- **No personal data** is required or solicited; the only credential is an anonymous resume code
  (stored hashed). Crisis prompts route to localized help resources, not AI counseling.

## 🧪 Tests

```bash
cd backend && .venv/Scripts/python.exe -m pytest          # backend
cd frontend && npm run test                                # frontend (vitest)
```

## 📁 Layout

```
backend/   FastAPI app (core, db, models, schemas, sanitization, llm, visuals, services, api) + tests
frontend/  Vue SPA (views, components, stores, composables, lib, types, style, locales)
infra/     Docker Compose, Dockerfiles, nginx, deploy/update/dev scripts
docs/      Architecture design + research
SPEC.md    Frozen architecture (source of truth)
```
