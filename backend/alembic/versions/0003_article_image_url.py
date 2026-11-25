"""Preserve publisher article image metadata independently of summary status."""

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("image_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "image_url")
