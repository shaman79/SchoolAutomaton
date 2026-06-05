"""Layered sanitize → classify → validate pipeline (SPEC §5). The single entrypoint for untrusted
student text. Orchestrates the six layers:

  L0 ratelimit   — per-ip_hash token bucket (HTTP 429 when exceeded)
  L1 preprocess  — deterministic NFKC + strip invisibles/bidi/controls + advisory heuristics
  L2 classifier  — Haiku 4.5 (or deterministic fallback) → StructuredIntent, never obeys the text
  L3 validate    — deterministic re-validate + re-sanitize + route to a Decision (breakout containment)
  L4 safety      — child-safety + crisis-resource selection (used inside validate)
  L5 audit       — async audit row; no raw text by default; topic hashed; Fernet raw only on flag

INVARIANT: the returned Decision carries only a validated StructuredIntent — never raw text — and
nothing downstream ever receives the raw prompt (``tests/test_no_raw_leak.py``)."""

from __future__ import annotations

import time

from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..core.security import sha256_hex
from ..schemas.intent import CrisisDecision, Decision, RefuseDecision
from . import audit, classifier, preprocess, ratelimit, validate

__all__ = ["sanitize_request"]


async def sanitize_request(
    db: AsyncSession,
    raw_prompt: str,
    ctx: RequestContext,
    request_id: str,
) -> Decision:
    """Run the 6-layer pipeline and return a routing Decision
    (proceed | clarify | refuse | crisis). Writes a sanitization_audit row (no raw text by default)."""
    started = time.monotonic()

    # L0 — rate limit (raises HTTP 429 when exceeded). Keyed on the salted ip_hash.
    ratelimit.check(ctx)

    # L1 — deterministic preprocess (pure, un-injectable).
    pre = preprocess.preprocess(raw_prompt)

    # L2 — classify cleaned text (LLM if available, else deterministic fallback).
    raw_intent = await classifier.classify(pre.clean_text, pre)

    # L3/L4 — deterministic validate + route (re-validates enums, re-sanitizes topic, selects crisis
    # resources). The Decision carries only the validated StructuredIntent.
    decision = validate.build_decision(raw_intent, request_id)

    # The validated/sanitized intent that actually leaves the pipeline (used for the audit verdict).
    validated_intent = validate.revalidate_intent(raw_intent)

    # Abuse signal: count an injection strike when an override was detected.
    if validated_intent.injection_detected:
        ratelimit.limiter.record_strike(ctx)

    latency_ms = int((time.monotonic() - started) * 1000)

    # L5 — audit (best-effort; never breaks the request). Raw text only when configured AND flagged.
    flagged = bool(validated_intent.safety_flags) or isinstance(
        decision, (CrisisDecision, RefuseDecision)
    )
    await audit.write_audit(
        db,
        request_id=request_id,
        ip_hash=ctx.ip_hash,
        hashed_profile_id=sha256_hex(str(ctx.profile_id)) if ctx.profile_id is not None else None,
        raw_length=len(raw_prompt or ""),
        removed_char_summary=pre.removed_char_summary,
        suspicion_score=pre.suspicion_score,
        heuristic_hit_ids=pre.heuristic_hit_ids,
        intent=validated_intent,
        decision=decision,
        latency_ms=latency_ms,
        raw_prompt=raw_prompt if flagged else None,
    )

    return decision
