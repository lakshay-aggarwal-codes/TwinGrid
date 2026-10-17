"""Data access for maintenance work orders (Task 28). Same rule as data_repository: route code never builds a row."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import WorkOrder, WorkOrderEvent
from src import work_orders as rules
from src.timeutil import utc_now

_UNSET: Any = object()


async def create_order(
    session: AsyncSession,
    *,
    created_by: str,
    title: str,
    description: Optional[str],
    priority: str,
    assignee: Optional[str],
    asset_external_id: Optional[str],
    source_kind: str,
    source_ref: Optional[str],
) -> WorkOrder:
    now = utc_now()
    row = WorkOrder(
        created_at=now,
        updated_at=now,
        created_by=created_by,
        title=title,
        description=description,
        priority=priority,
        status=rules.OPEN,
        assignee=assignee,
        asset_external_id=asset_external_id,
        source_kind=source_kind,
        source_ref=source_ref,
        origin=rules.origin_for(source_kind),  # the simulator never writes "measured"
    )
    session.add(row)
    await session.flush()
    session.add(
        WorkOrderEvent(
            work_order_id=row.id,
            created_at=now,
            actor=created_by,
            kind="created",
            to_status=rules.OPEN,
            assignee=assignee,
        )
    )
    await session.flush()
    return row


async def get_order(session: AsyncSession, order_id: int) -> Optional[WorkOrder]:
    return await session.get(WorkOrder, order_id)


async def list_orders(
    session: AsyncSession, limit: int, status: Optional[str] = None, asset_external_id: Optional[str] = None
) -> list[WorkOrder]:
    stmt = select(WorkOrder).order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc())
    if status is not None:
        stmt = stmt.where(WorkOrder.status == status)
    if asset_external_id is not None:
        stmt = stmt.where(WorkOrder.asset_external_id == asset_external_id)
    return list((await session.execute(stmt.limit(limit))).scalars().all())


async def list_events(session: AsyncSession, order_id: int) -> list[WorkOrderEvent]:
    stmt = (
        select(WorkOrderEvent)
        .where(WorkOrderEvent.work_order_id == order_id)
        .order_by(WorkOrderEvent.created_at, WorkOrderEvent.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def change_status(
    session: AsyncSession, order_id: int, *, actor: str, to_status: str, note: Optional[str]
) -> Optional[WorkOrder]:
    """Move to ``to_status``. ``None`` if missing; ``rules.TransitionError`` (nothing changed) if not allowed."""
    row = await session.get(WorkOrder, order_id)
    if row is None:
        return None
    rules.check_transition(row.status, to_status)
    now = utc_now()
    previous = row.status
    row.status = to_status
    row.updated_at = now
    session.add(
        WorkOrderEvent(
            work_order_id=row.id,
            created_at=now,
            actor=actor,
            kind="status",
            from_status=previous,
            to_status=to_status,
            assignee=row.assignee,
            note=note,
        )
    )
    await session.flush()
    return row


async def edit_order(
    session: AsyncSession,
    order_id: int,
    *,
    actor: str,
    title: Any = _UNSET,
    description: Any = _UNSET,
    priority: Any = _UNSET,
    assignee: Any = _UNSET,
) -> tuple[Optional[WorkOrder], list[str]]:
    """Change the given fields of an order that is not final. Returns ``(row, changed field names)``.

    ``None`` if missing; ``rules.TransitionError("final")`` for a done or cancelled order.
    An unchanged value is not a change.
    """
    row = await session.get(WorkOrder, order_id)
    if row is None:
        return None, []
    if row.status in rules.FINAL_STATUSES:
        raise rules.TransitionError("final")
    changed: list[str] = []
    for name, value in (("title", title), ("description", description), ("priority", priority), ("assignee", assignee)):
        if value is not _UNSET and getattr(row, name) != value:
            setattr(row, name, value)
            changed.append(name)
    if changed:
        now = utc_now()
        row.updated_at = now
        session.add(
            WorkOrderEvent(
                work_order_id=row.id,
                created_at=now,
                actor=actor,
                kind="edit",
                assignee=row.assignee,
                note="changed: " + ", ".join(changed),
            )
        )
        await session.flush()
    return row, changed


UNSET = _UNSET
