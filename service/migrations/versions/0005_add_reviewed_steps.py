"""Keep explicitly reviewed categories separate from unfinished draft work.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-18

Legacy rows get no review assertions. A saved polygon never proves that the
contributor reviewed every other feature category.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("saved_holes") as batch:
        batch.add_column(sa.Column(
            "reviewed_steps", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False, server_default="[]",
        ))


def downgrade() -> None:
    with op.batch_alter_table("saved_holes") as batch:
        batch.drop_column("reviewed_steps")
