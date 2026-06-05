"""Layered sanitize → classify → validate pipeline (SPEC §5). The single entrypoint for untrusted
student text. The LLM is authoritative for intent; the deterministic layers are MINIMAL guards:

  L0 ratelimit   — per-ip_hash token bucket (HTTP 429 when exceeded)
  L1 preprocess  — NFKC + strip invisibles/bidi/controls + flag injection patterns (advisory)
  L1.5 safety net— tiny deterministic self-harm check → force crisis (works even if the LLM is down)
  L2 classifier  — Haiku 4.5 understands the intent (subject/topic/grade/language/study-test/safety).
                   FAILS CLOSED if unavailable — no keyword guessing.
  L3 validate    — deterministic re-validate + scrub injection lead-ins out of the topic + route
  L4 safety      — child-safety routing + localized crisis resources (used inside validate)
  L5 audit       — async audit row; no raw text by default; topic hashed; Fernet raw only on flag

INVARIANT: the returned Decision carries only a validated StructuredIntent — never raw text — and
nothing downstream ever receives the raw prompt (``tests/test_no_raw_leak.py``)."""

from __future__ import annotations

import logging
import time

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..core.security import sha256_hex
from ..schemas.enums import SafetyFlag
from ..schemas.intent import CrisisDecision, Decision, RefuseDecision, StructuredIntent
from . import audit, classifier, preprocess, ratelimit, safety, validate

__all__ = ["sanitize_request"]

logger = logging.getLogger("schoolautomaton.sanitization")

_UNAVAILABLE_MSG = {
    "en": "Sorry — the learning assistant is temporarily unavailable. Please try again in a moment.",
    "cs": "Omlouváme se — vzdělávací asistent je dočasně nedostupný. Zkuste to prosím za chvíli.",
}


async def sanitize_request(
    db: AsyncSession,
    raw_prompt: str,
    ctx: RequestContext,
    request_id: str,
) -> Decision:
    """Run the pipeline and return a routing Decision (proceed | clarify | refuse | crisis).

    Raises HTTP 429 (rate limit) or HTTP 503 (assistant unavailable — fail closed, no guessing)."""
    started = time.monotonic()

    # L0 — rate limit (raises HTTP 429 when exceeded). Keyed on the salted ip_hash.
    ratelimit.check(ctx)

    # L1 — deterministic preprocess (pure, un-injectable).
    pre = preprocess.preprocess(raw_prompt)

    # L1.5 — minimal deterministic self-harm net: force crisis even if the LLM never runs.
    if safety.looks_like_crisis(pre.clean_text):
        lang = classifier.detect_language(pre.clean_text)
        net_intent = StructuredIntent(
            safety_flags=[SafetyFlag.SELF_HARM], language=lang, is_educational=False
        )
        decision = validate.build_decision(net_intent, request_id)
        await _audit(db, request_id, ctx, raw_prompt, pre, net_intent, decision, started, flagged=True)
        return decision

    # L2 — the LLM classifies intent. Fail CLOSED if it can't run (no key / transient failure).
    try:
        raw_intent = await classifier.classify(pre.clean_text, pre)
    except classifier.ClassifierUnavailable as exc:
        logger.warning("Classifier unavailable for %s: %s", request_id, exc)
        lang = classifier.detect_language(pre.clean_text)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, _UNAVAILABLE_MSG.get(lang, _UNAVAILABLE_MSG["en"])
        ) from exc

    # L3/L4 — deterministic validate + route (re-validate enums, scrub topic, select crisis resources).
    decision = validate.build_decision(raw_intent, request_id)
    validated_intent = validate.revalidate_intent(raw_intent)

    if validated_intent.injection_detected:
        ratelimit.limiter.record_strike(ctx)

    flagged = bool(validated_intent.safety_flags) or isinstance(
        decision, (CrisisDecision, RefuseDecision)
    )
    await _audit(db, request_id, ctx, raw_prompt, pre, validated_intent, decision, started, flagged)
    return decision


async def _audit(db, request_id, ctx, raw_prompt, pre, intent, decision, started, flagged) -> None:
    """L5 — best-effort audit row (never breaks the request). Raw text only when configured AND flagged."""
    latency_ms = int((time.monotonic() - started) * 1000)
    await audit.write_audit(
        db,
        request_id=request_id,
        ip_hash=ctx.ip_hash,
        hashed_profile_id=sha256_hex(str(ctx.profile_id)) if ctx.profile_id is not None else None,
        raw_length=len(raw_prompt or ""),
        removed_char_summary=pre.removed_char_summary,
        suspicion_score=pre.suspicion_score,
        heuristic_hit_ids=pre.heuristic_hit_ids,
        intent=intent,
        decision=decision,
        latency_ms=latency_ms,
        raw_prompt=raw_prompt if flagged else None,
    )
