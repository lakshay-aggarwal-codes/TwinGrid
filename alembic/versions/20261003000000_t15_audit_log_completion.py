"""T15: audit-log completion -- outcome / request_id / client_ip + PostgreSQL append-only trigger.

Revision ID: 20261003000000
Revises: 20261002000000
Create Date: 2026-10-03

Schema (audit_logs):
  * ``outcome``    varchar(16) NOT NULL DEFAULT 'success', CHECK outcome IN ('success','denied','failure').
                   Every pre-existing row is therefore backfilled ``success`` (those rows were only ever
                   written for actions that went ahead).
  * ``request_id`` varchar(64) NULL, indexed (``ix_audit_logs_request_id``). Legacy rows stay NULL.
  * ``client_ip``  = the former ``ip_address`` column, renamed (data preserved).

PostgreSQL only: trigger ``audit_logs_append_only`` (BEFORE UPDATE OR DELETE, per row) calls
``audit_logs_forbid_mutation()`` which raises SQLSTATE 23001 (restrict_violation). Single exception: an
UPDATE that changes ONLY ``user_id`` from non-NULL to NULL, which is what ``ON DELETE SET NULL`` does when a
user account is deleted (the denormalized ``username`` keeps the row readable). The trigger is created LAST on
upgrade and dropped FIRST on downgrade, so no UPDATE of the table ever runs while it is active.

Guarantee / non-guarantee: this stops UPDATE/DELETE through normal DML for any role. A superuser or the table
owner can still ``ALTER TABLE ... DISABLE TRIGGER``, drop it, or TRUNCATE. It is NOT immutability against a
database superuser. TRUNCATE is deliberately not trapped (it would also block test/dev resets).

Restore ordering: ``pg_dump``/``pg_restore`` load table data before triggers are (re)created, so a restore into
an empty schema works. A restore that replays INSERTs after the trigger exists is fine (INSERT is allowed);
anything that UPDATEs audit rows during a restore will be refused -- by design.

SQLite (test suite / local dev) has no trigger: UPDATE/DELETE are NOT blocked there. See
tests/test_audit_migration.py, which asserts and documents that.

Rollback: ``alembic downgrade -1`` drops the trigger and function, then removes the index, the CHECK, ``outcome``
and ``request_id``, and renames ``client_ip`` back to ``ip_address``. Only the two new columns' data is lost.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261003000000"
down_revision: Union[str, None] = "20261002000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK_NAME = "ck_audit_logs_outcome"
INDEX_NAME = "ix_audit_logs_request_id"
TRIGGER_NAME = "audit_logs_append_only"
FUNCTION_NAME = "audit_logs_forbid_mutation"

# Exposed so the PostgreSQL test can install exactly what the migration installs.
CREATE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNCTION_NAME}() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.user_id IS NOT NULL AND NEW.user_id IS NULL
       AND (to_jsonb(NEW) - 'user_id') = (to_jsonb(OLD) - 'user_id') THEN
        RETURN NEW;  -- ON DELETE SET NULL of users.id: the only permitted change
    END IF;
    RAISE EXCEPTION 'audit_logs is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""
CREATE_TRIGGER_SQL = f"""
CREATE TRIGGER {TRIGGER_NAME}
BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION {FUNCTION_NAME}();
"""
DROP_TRIGGER_SQL = f"DROP TRIGGER IF EXISTS {TRIGGER_NAME} ON audit_logs"
DROP_FUNCTION_SQL = f"DROP FUNCTION IF EXISTS {FUNCTION_NAME}()"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    with op.batch_alter_table("audit_logs") as batch:
        batch.alter_column(
            "ip_address", new_column_name="client_ip", existing_type=sa.String(64), existing_nullable=True
        )
        # NOT NULL + constant server_default: every existing row becomes 'success'.
        batch.add_column(sa.Column("outcome", sa.String(16), nullable=False, server_default="success"))
        batch.add_column(sa.Column("request_id", sa.String(64), nullable=True))
        batch.create_check_constraint(CHECK_NAME, "outcome IN ('success', 'denied', 'failure')")
        batch.create_index(INDEX_NAME, ["request_id"], unique=False)

    if _is_postgres():  # last: nothing UPDATEs audit_logs after this point
        op.execute(CREATE_FUNCTION_SQL)
        op.execute(CREATE_TRIGGER_SQL)


def downgrade() -> None:
    if _is_postgres():  # first: the table must be mutable again before it is altered
        op.execute(DROP_TRIGGER_SQL)
        op.execute(DROP_FUNCTION_SQL)

    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_index(INDEX_NAME)
        batch.drop_constraint(CHECK_NAME, type_="check")
        batch.drop_column("request_id")
        batch.drop_column("outcome")
        batch.alter_column(
            "client_ip", new_column_name="ip_address", existing_type=sa.String(64), existing_nullable=True
        )
