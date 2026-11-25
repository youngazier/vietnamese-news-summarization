"""Record the latest human decision independently of AI review feedback."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("summaries", sa.Column("human_review_decision", sa.String(10), nullable=True))
    op.add_column("summaries", sa.Column("human_review_note", sa.Text(), nullable=True))
    op.add_column(
        "summaries", sa.Column("human_reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_summaries_human_review"),
        "summaries",
        "human_review_decision IS NULL OR (human_reviewed_at IS NOT NULL AND "
        "((human_review_decision = 'accept' AND approved) OR "
        "(human_review_decision = 'decline' AND NOT approved AND human_review_note IS NOT NULL "
        "AND length(trim(human_review_note)) > 0)))",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_summaries_human_review"), "summaries", type_="check")
    op.drop_column("summaries", "human_reviewed_at")
    op.drop_column("summaries", "human_review_note")
    op.drop_column("summaries", "human_review_decision")
