"""add cancelled enum

Revision ID: 615962053c1e
Revises: 9142a65df02f
Create Date: 2026-02-02 23:41:18.469791

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '615962053c1e'
down_revision: Union[str, Sequence[str], None] = '9142a65df02f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    """
    Update the Postgres Enum type to include 'CANCELLED'.
    Note: 'ALTER TYPE ... ADD VALUE' cannot run inside a transaction block.
    """
    bind = op.get_bind()

    # Check if we are using PostgreSQL
    if bind.dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE productversionstatus ADD VALUE IF NOT EXISTS 'CANCELLED'")
    else:
        # Fallback for SQLite/MySQL if you are using them locally.
        # SQLite doesn't support altering constraints easily; it requires batch migration.
        # This is a soft-pass for SQLite assuming app-level validation handles it.
        pass


def downgrade():
    """
    Revert the Enum change.
    PostgreSQL does NOT support 'DROP VALUE' from an Enum. 
    We must rename the old type, create a new one, migrate data, and drop the old type.
    """
    bind = op.get_bind()

    if bind.dialect.name == 'postgresql':
        # 1. Rename the current (new) type to something temporary
        op.execute(
            "ALTER TYPE productversionstatus RENAME TO productversionstatus_old")

        # 2. Create the old type definition (WITHOUT 'CANCELLED')
        # Ensure these match your previous Enum definition exactly
        op.execute(
            "CREATE TYPE productversionstatus AS ENUM('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED')")

        # 3. Handle data that might be 'CANCELLED' before converting
        # We map 'CANCELLED' back to 'REJECTED' (or delete) to prevent casting errors
        op.execute(
            "UPDATE productversion SET status = 'REJECTED' WHERE status::text = 'CANCELLED'")

        # 4. Update the column to use the new type
        op.execute((
            "ALTER TABLE productversion "
            "ALTER COLUMN status TYPE productversionstatus "
            "USING status::text::productversionstatus"
        ))

        # 5. Drop the old type
        op.execute("DROP TYPE productversionstatus_old")
    else:
        pass
