"""FSRS-due review session builder with interleaving (SPEC pedagogy). Implemented by the **B4 agent**.

Composition ~55% current / 25% related / 20% prereq (INTERLEAVE_COMPOSITION), shuffled so consecutive
items differ in concept/type; daily new-item cap per age band (DAILY_NEW_CAP) + all overdue. Keep
this signature.

The session is built from the learner's per-profile FSRS cards (item_fsrs_cards): all overdue cards
are always surfaced, plus up to DAILY_NEW_CAP brand-new cards. The composition then biases the buckets
toward the learner's most-active "current" concept, its ``related`` neighbours and its
``prerequisite`` refreshers via concept_edges. Ordering is a deterministic interleave so consecutive
items differ in concept and item-type (design pedagogy_framework: INTERLEAVING)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.constants import DAILY_NEW_CAP, INTERLEAVE_COMPOSITION
from ..models import Concept, ConceptEdge, Item, ItemFsrsCard, Profile
from ..schemas.gamification import ReviewComposition

_DEFAULT_LIMIT = 20


async def _concept_neighbourhood(
    db: AsyncSession, concept_ids: set[int]
) -> tuple[set[int], set[int]]:
    """Return (related_ids, prereq_ids) for the given concepts via concept_edges.

    related: undirected ``related`` edges. prereq: ``prerequisite`` edges pointing INTO a concept
    (from_concept is the prerequisite of to_concept)."""
    if not concept_ids:
        return set(), set()
    edges = (
        await db.execute(
            select(
                ConceptEdge.from_concept_id, ConceptEdge.to_concept_id, ConceptEdge.edge_type
            )
        )
    ).all()
    related: set[int] = set()
    prereq: set[int] = set()
    for frm, to, etype in edges:
        if etype == "related":
            if frm in concept_ids:
                related.add(to)
            if to in concept_ids:
                related.add(frm)
        elif etype == "prerequisite" and to in concept_ids:
            prereq.add(frm)
    related -= concept_ids
    prereq -= concept_ids
    return related, prereq


def _interleave(items: list[Item]) -> list[Item]:
    """Reorder so consecutive items differ in concept (and, where possible, item type).

    Greedy: repeatedly pick the next item whose concept differs from the previous one; break ties by
    differing item-type, then by the original (due-priority) order. Deterministic — no RNG."""
    remaining = list(items)
    out: list[Item] = []
    prev_concept: int | None = None
    prev_type: str | None = None
    while remaining:
        choice_idx = 0
        for idx, it in enumerate(remaining):
            if it.concept_id != prev_concept:
                if it.item_type != prev_type:
                    choice_idx = idx
                    break
                if choice_idx == 0 and remaining[0].concept_id == prev_concept:
                    choice_idx = idx
        else:
            choice_idx = 0  # all share prev_concept — keep priority order
        # Prefer a differing-concept candidate even if no differing-type one was found.
        if remaining[choice_idx].concept_id == prev_concept:
            alt = next((i for i, it in enumerate(remaining) if it.concept_id != prev_concept), None)
            if alt is not None:
                choice_idx = alt
        chosen = remaining.pop(choice_idx)
        out.append(chosen)
        prev_concept = chosen.concept_id
        prev_type = chosen.item_type
    return out


async def build_review_session(
    db: AsyncSession,
    profile: Profile,
    limit: int | None = None,
    subject: str | None = None,
) -> tuple[list[Item], ReviewComposition]:
    """Return (ordered Items for review, composition actually used)."""
    now = datetime.now(UTC)
    cap = limit or _DEFAULT_LIMIT
    new_cap = DAILY_NEW_CAP.get(profile.age_band, DAILY_NEW_CAP["unknown"])

    # All of the learner's cards joined to their items (optionally subject-filtered).
    stmt = (
        select(ItemFsrsCard, Item)
        .join(Item, Item.id == ItemFsrsCard.item_id)
        .where(ItemFsrsCard.profile_id == profile.id)
    )
    if subject:
        stmt = stmt.join(Concept, Concept.id == Item.concept_id).where(Concept.subject == subject)
    rows = (await db.execute(stmt)).all()

    overdue: list[tuple[datetime, Item]] = []
    new_items: list[Item] = []
    for card, item in rows:
        if card.state == 0 or card.due is None:
            new_items.append(item)
            continue
        due = card.due if card.due.tzinfo else card.due.replace(tzinfo=UTC)
        if due <= now:
            overdue.append((due, item))

    # Overdue first (earliest due first — always surfaced, never capped), then capped new items.
    overdue.sort(key=lambda t: (t[0], t[1].id))
    due_items = [it for _due, it in overdue]
    new_items.sort(key=lambda it: it.id)
    new_items = new_items[:new_cap]

    candidates = due_items + new_items
    if not candidates:
        return [], ReviewComposition(**INTERLEAVE_COMPOSITION)

    # "Current" concept = the most-represented due concept (the learner's active focus).
    concept_counts: dict[int, int] = {}
    for it in due_items or candidates:
        concept_counts[it.concept_id] = concept_counts.get(it.concept_id, 0) + 1
    current_concepts = {max(concept_counts, key=lambda c: (concept_counts[c], -c))} if concept_counts else set()
    related_ids, prereq_ids = await _concept_neighbourhood(db, current_concepts)

    # Bucket candidates by relationship to the current concept.
    cur_bucket, rel_bucket, pre_bucket, other = [], [], [], []
    for it in candidates:
        if it.concept_id in current_concepts:
            cur_bucket.append(it)
        elif it.concept_id in related_ids:
            rel_bucket.append(it)
        elif it.concept_id in prereq_ids:
            pre_bucket.append(it)
        else:
            other.append(it)

    comp = INTERLEAVE_COMPOSITION
    n_current = round(cap * comp["current"])
    n_related = round(cap * comp["related"])
    n_prereq = cap - n_current - n_related  # remainder → prereq share

    selected: list[Item] = []
    selected += cur_bucket[:n_current]
    selected += rel_bucket[:n_related]
    selected += pre_bucket[:n_prereq]

    # Backfill from any remaining candidates (overdue priority preserved) up to the cap.
    chosen_ids = {it.id for it in selected}
    for it in cur_bucket + rel_bucket + pre_bucket + other:
        if len(selected) >= cap:
            break
        if it.id not in chosen_ids:
            selected.append(it)
            chosen_ids.add(it.id)

    selected = selected[:cap]
    used_total = len(selected) or 1
    composition = ReviewComposition(
        current=round(sum(1 for it in selected if it.concept_id in current_concepts) / used_total, 3),
        related=round(sum(1 for it in selected if it.concept_id in related_ids) / used_total, 3),
        prereq=round(sum(1 for it in selected if it.concept_id in prereq_ids) / used_total, 3),
    )

    ordered = _interleave(selected)
    return ordered, composition
