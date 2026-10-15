"""chunks.fts: generated tsvector + GIN index for the keyword leg (decision 25)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE chunks ADD COLUMN fts tsvector GENERATED ALWAYS AS "
        "(to_tsvector('english', coalesce(header, '') || ' ' || coalesce(text, ''))) STORED"
    )
    op.execute("CREATE INDEX ix_chunks_fts ON chunks USING gin (fts)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_chunks_fts")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS fts")
