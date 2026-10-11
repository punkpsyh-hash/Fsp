"""Добавление банков, неизменяемых версий, ответов и очереди runner."""
from alembic import op
import sqlalchemy as sa

revision = 'b472f8c2e901'
down_revision = 'a3518c9b3b38'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('task_banks',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('owner_id', sa.String(64), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('external_id', sa.String(120), nullable=False),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('scope', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'external_id'))
    op.create_index('ix_task_banks_owner_id', 'task_banks', ['owner_id'])
    op.create_table('bank_versions',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('bank_id', sa.String(64), sa.ForeignKey('task_banks.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(20), nullable=False),
        sa.Column('document', sa.JSON(), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('bank_id', 'number'))
    op.create_index('ix_bank_versions_bank_id', 'bank_versions', ['bank_id'])
    op.create_table('bank_imports',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('owner_id', sa.String(64), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('filename', sa.String(200), nullable=False),
        sa.Column('document', sa.JSON(), nullable=True),
        sa.Column('errors', sa.JSON(), nullable=False),
        sa.Column('warnings', sa.JSON(), nullable=False),
        sa.Column('bank_id', sa.String(64), sa.ForeignKey('task_banks.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'content_hash'))
    op.create_index('ix_bank_imports_owner_id', 'bank_imports', ['owner_id'])
    op.create_table('bank_attempts',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('candidate_id', sa.String(64), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('version_id', sa.String(64), sa.ForeignKey('bank_versions.id'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('answers', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deadline', sa.DateTime(timezone=True), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('candidate_id', 'version_id'))
    op.create_index('ix_bank_attempts_candidate_id', 'bank_attempts', ['candidate_id'])
    op.create_index('ix_bank_attempts_version_id', 'bank_attempts', ['version_id'])
    op.create_table('bank_code_jobs',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('attempt_id', sa.String(64), sa.ForeignKey('bank_attempts.id'), nullable=False),
        sa.Column('task_id', sa.String(80), nullable=False),
        sa.Column('source', sa.String(32000), nullable=False),
        sa.Column('source_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error_code', sa.String(40), nullable=True),
        sa.Column('lease_token_hash', sa.String(64), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retries', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_bank_code_jobs_attempt_id', 'bank_code_jobs', ['attempt_id'])
    op.create_index('ix_bank_code_jobs_status', 'bank_code_jobs', ['status'])
    op.create_table('bank_reviews',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('attempt_id', sa.String(64), sa.ForeignKey('bank_attempts.id'), nullable=False),
        sa.Column('task_id', sa.String(80), nullable=False),
        sa.Column('reviewer_id', sa.String(64), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('feedback', sa.String(4000), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('attempt_id', 'task_id'))
    op.create_index('ix_bank_reviews_attempt_id', 'bank_reviews', ['attempt_id'])


def downgrade():
    for table in ['bank_reviews', 'bank_code_jobs', 'bank_attempts', 'bank_imports', 'bank_versions', 'task_banks']:
        op.drop_table(table)
