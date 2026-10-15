"""initial schema: acts, source_files, sections, chunks, ipc_bns_mapping

No vector index on purpose (decision 20: exact search at ~1k rows).

Revision ID: 0001
Revises:
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIM = 384


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "acts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("short_name", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("jurisdiction", sa.String(32), nullable=False),
        sa.Column("version_note", sa.Text),
        sa.Column("effective_from", sa.Date),
        sa.Column("effective_to", sa.Date),
        sa.Column("superseded_by", sa.Integer, sa.ForeignKey("acts.id")),
    )
    op.create_table(
        "source_files",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("act_id", sa.Integer, sa.ForeignKey("acts.id")),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("page_count", sa.Integer, nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
    )
    op.create_table(
        "sections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("act_id", sa.Integer, sa.ForeignKey("acts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_file_id", sa.Integer, sa.ForeignKey("source_files.id"), nullable=False),
        sa.Column("anchor", sa.String(96), nullable=False, unique=True),
        sa.Column("number", sa.String(16), nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("title_source", sa.String(32)),
        sa.Column("chapter", sa.String(16)),
        sa.Column("chapter_title", sa.Text),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("page_start", sa.Integer, nullable=False),
        sa.Column("page_end", sa.Integer, nullable=False),
        sa.Column("char_start", sa.Integer, nullable=False),
        sa.Column("char_end", sa.Integer, nullable=False),
        sa.Column("segments", sa.JSON, nullable=False),
        sa.UniqueConstraint("act_id", "number", name="uq_section_act_number"),
    )
    op.create_index("ix_sections_act_id", "sections", ["act_id"])
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("section_id", sa.Integer, sa.ForeignKey("sections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_no", sa.Integer, nullable=False),
        sa.Column("header", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("char_start", sa.Integer, nullable=False),
        sa.Column("char_end", sa.Integer, nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.UniqueConstraint("section_id", "chunk_no", name="uq_chunk_section_no"),
    )
    op.create_index("ix_chunks_section_id", "chunks", ["section_id"])
    op.create_table(
        "ipc_bns_mapping",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_file_id", sa.Integer, sa.ForeignKey("source_files.id"), nullable=False),
        sa.Column("bns_ref", sa.String(32), nullable=False),
        sa.Column("bns_section", sa.Integer, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("ipc_ref", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("page", sa.Integer, nullable=False),
    )
    op.create_index("ix_mapping_bns_section", "ipc_bns_mapping", ["bns_section"])


def downgrade():
    op.drop_table("ipc_bns_mapping")
    op.drop_table("chunks")
    op.drop_table("sections")
    op.drop_table("source_files")
    op.drop_table("acts")
