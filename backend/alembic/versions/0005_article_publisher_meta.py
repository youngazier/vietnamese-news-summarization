"""Store publisher metadata gathered during HTML extraction."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("publisher_meta", JSONB(none_as_null=True), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "publisher_meta")
