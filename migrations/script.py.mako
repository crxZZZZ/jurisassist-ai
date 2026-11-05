"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""
from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    ${upgrades if upgrades else "pass"}
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE INDEX ix_chunks_fts ON chunks USING gin (to_tsvector('portuguese', text))")
        op.execute("CREATE INDEX ix_chunks_vector ON chunks USING hnsw (embedding vector_cosine_ops)")

def downgrade():
    ${downgrades if downgrades else "pass"}
