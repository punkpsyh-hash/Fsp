"""Сигналы добросовестности попытки и уровень у подтверждённого профиля."""
from alembic import op
import sqlalchemy as sa

revision = 'e8a1c4d27f03'
down_revision = 'd795a01be238'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('attempts', sa.Column('integrity', sa.JSON(), nullable=True))
    op.add_column('profiles', sa.Column('integrity_level', sa.String(length=10), nullable=True))
    op.create_index('ix_profiles_search', 'profiles', ['published', 'specialization', 'confirmed_grade'])
    op.create_table(
        'fsp_flows',
        sa.Column('state', sa.String(length=64), primary_key=True),
        sa.Column('user_id', sa.String(length=64), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('verifier', sa.String(length=128), nullable=False),
        sa.Column('challenge', sa.String(length=64), nullable=False),
        sa.Column('code_hash', sa.String(length=64), nullable=True, index=True),
        sa.Column('member_id', sa.String(length=80), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False),
    )


def downgrade():
    op.drop_table('fsp_flows')
    op.drop_index('ix_profiles_search', table_name='profiles')
    op.drop_column('profiles', 'integrity_level')
    op.drop_column('attempts', 'integrity')
