"""Data access for optimizer proposals (Task 19). Same rule as data_repository: route code never builds a row."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import OptimizerProposal
from src import optimizer_proposals as rules
from src.timeutil import utc_now


async def create_proposal(
    session: AsyncSession,
    *,
    proposer: str,
    source: str,
    chilled_water_temp_c: float,
    cooling_mode: str,
    context: dict[str, Any],
    predicted: dict[str, Any],
    rationale: Optional[str],
) -> OptimizerProposal:
    row = OptimizerProposal(
        proposer=proposer,
        source=source,
        chilled_water_temp_c=chilled_water_temp_c,
        cooling_mode=cooling_mode,
        context=context,
        predicted=predicted,
        rationale=rationale,
        origin="simulated",  # the prediction is a twin run; the simulator never writes "measured"
        status=rules.PENDING,
    )
    session.add(row)
    await session.flush()
    return row


async def list_proposals(session: AsyncSession, limit: int, status: Optional[str] = None) -> list[OptimizerProposal]:
    stmt = select(OptimizerProposal).order_by(OptimizerProposal.created_at.desc(), OptimizerProposal.id.desc())
    if status is not None:
        stmt = stmt.where(OptimizerProposal.status == status)
    return list((await session.execute(stmt.limit(limit))).scalars().all())


async def decide(
    session: AsyncSession, proposal_id: int, *, decider: str, decision: str, note: Optional[str]
) -> Optional[OptimizerProposal]:
    """Record approve/reject. ``None`` if missing. Raises ``rules.DecisionError`` (nothing changed) when not allowed."""
    row = await session.get(OptimizerProposal, proposal_id)
    if row is None:
        return None
    rules.check_decision(row.status, row.proposer, decider)
    row.status = rules.DECISIONS[decision]
    row.decided_by = decider
    row.decided_at = utc_now()
    row.decision_note = note
    await session.flush()
    return row
