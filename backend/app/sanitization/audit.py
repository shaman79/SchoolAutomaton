"""Layer 5 — async sanitization audit (SPEC §5). Records one ``sanitization_audit`` row per request.

Privacy rules (COPPA-aligned):
  * NO raw student text is stored by default.
  * The topic is HASHED (sha256) inside ``classifier_verdict_json`` — never stored in clear.
  * The Fernet-encrypted raw prompt is retained ONLY when ``settings.raw_capture_on_flag`` is true AND
    a safety flag fired (crisis or refuse-worthy). It is purged after ``audit_raw_retention_days`` by
    an admin job (out of scope here).

The write is best-effort: an audit failure must never break the student's request, so callers run it
fire-and-forget and we swallow/rollback on error.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.constants import PROMPT_VERSION
from ..core.security import encrypt_secret, sha256_hex
from ..models import SanitizationAudit
from ..schemas.intent import (
    CrisisDecision,
    Decision,
    RefuseDecision,
    StructuredIntent,
)


def _hashed_verdict(intent: StructuredIntent) -> dict:
    """Serialize the classifier verdict for audit with the topic HASHED and constraints dropped."""
    data = intent.model_dump(mode="json")
    topic = data.get("topic") or ""
    data["topic"] = ""  # never store the clear topic
    data["topic_sha256"] = sha256_hex(topic) if topic else ""
    # Constraints are free text; keep only their count for audit, not the values.
    constraints = data.pop("constraints", []) or []
    data["constraints_count"] = len(constraints)
    return data


def _decision_reason(decision: Decision) -> str | None:
    if isinstance(decision, RefuseDecision):
        return decision.reason
    if isinstance(decision, CrisisDecision):
        return "crisis: self_harm"
    return None


async def write_audit(
    db: AsyncSession,
    *,
    request_id: str,
    ip_hash: str,
    hashed_profile_id: str | None,
    raw_length: int,
    removed_char_summary: dict | None,
    suspicion_score: float,
    heuristic_hit_ids: list[str] | None,
    intent: StructuredIntent,
    decision: Decision,
    latency_ms: int | None,
    raw_prompt: str | None = None,
    token_usage: dict | None = None,
) -> SanitizationAudit | None:
    """Persist a sanitization audit row. Returns the row (flushed) or None on failure."""
    safety_flags = [f.value for f in intent.safety_flags] if intent.safety_flags else []
    flagged = bool(safety_flags) or isinstance(decision, CrisisDecision)

    raw_encrypted: str | None = None
    if settings.raw_capture_on_flag and flagged and raw_prompt:
        # Only encrypted, only on a flagged event, only when explicitly enabled.
        raw_encrypted = encrypt_secret(raw_prompt)

    decision_type = (
        decision.type.value if hasattr(decision.type, "value") else str(decision.type)
    )

    row = SanitizationAudit(
        request_id=request_id,
        hashed_profile_id=hashed_profile_id,
        ip_hash=ip_hash,
        raw_length=raw_length,
        language=intent.language,
        removed_char_summary=removed_char_summary or {},
        suspicion_score=suspicion_score,
        heuristic_hit_ids=heuristic_hit_ids or [],
        classifier_verdict_json=_hashed_verdict(intent),
        decision_type=decision_type,
        reason=_decision_reason(decision),
        injection_detected=bool(intent.injection_detected),
        safety_flags=safety_flags,
        latency_ms=latency_ms,
        model_id=settings.sanitizer_model_id,
        prompt_version=PROMPT_VERSION,
        token_usage_json=token_usage,
        raw_prompt_encrypted=raw_encrypted,
    )
    try:
        db.add(row)
        await db.flush()
        return row
    except Exception:  # noqa: BLE001 — auditing must never break the request
        await db.rollback()
        return None


__all__ = ["write_audit"]
