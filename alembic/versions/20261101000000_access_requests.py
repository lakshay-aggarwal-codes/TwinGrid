"""T9: access_requests (visitor onboarding, contract 8.1).

Revision ID: 20261101000000
Revises: 20261008000000
Create Date: 2026-11-01

Additive only: one new table. ``uq_access_one_pending`` is a PARTIAL unique index (one pending request per normalised
email) and is created for both SQLite and PostgreSQL. Downgrade drops the table (and with it the index).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261101000000"
down_revision: Union[str, None] = "20261008000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "access_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ref", sa.String(16), nullable=False),
        sa.Column("email_normalized", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision_note", sa.String(500), nullable=True),
        sa.Column("status_token_hash", sa.String(64), nullable=False),
        sa.Column("activation_token_hash", sa.String(64), nullable=True),
        sa.Column("activation_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activation_consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notify_state", sa.String(16), nullable=False),
        sa.Column("notify_attempts", sa.Integer(), nullable=False),
        sa.Column("notify_last_code", sa.String(24), nullable=True),
        sa.Column("request_ip_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("ref", name="uq_access_requests_ref"),
    )
    op.create_index("ix_access_requests_email_normalized", "access_requests", ["email_normalized"])
    op.create_index("ix_access_requests_status_created", "access_requests", ["status", "created_at", "id"])
    op.create_index(
        "uq_access_one_pending",
        "access_requests",
        ["email_normalized"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_access_one_pending", table_name="access_requests")
    op.drop_index("ix_access_requests_status_created", table_name="access_requests")
    op.drop_index("ix_access_requests_email_normalized", table_name="access_requests")
    op.drop_table("access_requests")
