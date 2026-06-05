"""Knowledge-tree assembly for GET /profiles/me/tree. Reads the learner's skill_mastery rows + the
concept graph; mastery/state are maintained by the B4 gamification engine. Fully implemented."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Concept, ConceptEdge, Profile, SkillMastery
from ..schemas.enums import NodeState
from ..schemas.gamification import TreeEdge, TreeNode, TreeResponse


async def build_tree(
    db: AsyncSession, profile: Profile, subject: str | None = None
) -> TreeResponse:
    stmt = (
        select(SkillMastery, Concept)
        .join(Concept, Concept.id == SkillMastery.concept_id)
        .where(SkillMastery.profile_id == profile.id)
    )
    if subject:
        stmt = stmt.where(Concept.subject == subject)
    rows = (await db.execute(stmt)).all()
    concept_ids = {c.id for _, c in rows}

    prereq_of: dict[int, list[int]] = {}
    related_of: dict[int, list[int]] = {}
    edges: list[TreeEdge] = []
    if concept_ids:
        edge_rows = (
            await db.execute(
                select(ConceptEdge).where(
                    or_(
                        ConceptEdge.from_concept_id.in_(concept_ids),
                        ConceptEdge.to_concept_id.in_(concept_ids),
                    )
                )
            )
        ).scalars().all()
        for e in edge_rows:
            if e.from_concept_id in concept_ids and e.to_concept_id in concept_ids:
                edges.append(TreeEdge(from_id=e.from_concept_id, to_id=e.to_concept_id, type=e.edge_type))
            if e.edge_type == "prerequisite":
                prereq_of.setdefault(e.to_concept_id, []).append(e.from_concept_id)
            elif e.edge_type == "related":
                related_of.setdefault(e.from_concept_id, []).append(e.to_concept_id)
                related_of.setdefault(e.to_concept_id, []).append(e.from_concept_id)

    nodes: list[TreeNode] = []
    for sm, c in rows:
        state = sm.node_state if sm.node_state in NodeState._value2member_map_ else NodeState.AVAILABLE.value
        nodes.append(
            TreeNode(
                concept_id=c.id,
                title=c.name,
                subject=c.subject,
                mastery=sm.mastery,
                state=NodeState(state),
                prereq_ids=prereq_of.get(c.id, []),
                related_ids=sorted(set(related_of.get(c.id, []))),
                last_reviewed=sm.last_reviewed,
                decay_due_at=sm.decay_due_at,
            )
        )
    return TreeResponse(nodes=nodes, edges=edges)
