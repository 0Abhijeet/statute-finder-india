"""provision_status: curated struck-down / not-in-force flags (decision 40)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provision_status",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("act_short_name", sa.String(64), nullable=False),
        sa.Column("section", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("source_label", sa.Text, nullable=False),
        sa.Column("verification", sa.String(32), nullable=False),
        sa.UniqueConstraint("act_short_name", "section", name="uq_status_act_section"),
    )


def downgrade():
    op.drop_table("provision_status")
