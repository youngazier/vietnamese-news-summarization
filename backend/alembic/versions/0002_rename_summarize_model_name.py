"""Rename the summarization model column without changing existing values."""

from alembic import op

revision: str = "0002"
down_revision: str = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("summaries", "model_name", new_column_name="summarize_model_name")


def downgrade() -> None:
    op.alter_column("summaries", "summarize_model_name", new_column_name="model_name")
