"""Серверные черновики и неизменяемые объяснения без потери прежних попыток."""
from alembic import op
import sqlalchemy as sa

revision = 'c683e90a12d4'
down_revision = 'b472f8c2e901'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('attempts', sa.Column('question_form', sa.JSON(), nullable=True))
    op.add_column('attempts', sa.Column('answers', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('attempts', sa.Column('revision', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('search_snapshots', sa.Column('explanations', sa.JSON(), nullable=True))
    op.add_column('search_snapshots', sa.Column('algorithm_version', sa.String(50), nullable=False, server_default='weighted-v1'))


def downgrade():
    for name in ('algorithm_version', 'explanations'):
        op.drop_column('search_snapshots', name)
    for name in ('revision', 'answers', 'question_form'):
        op.drop_column('attempts', name)
