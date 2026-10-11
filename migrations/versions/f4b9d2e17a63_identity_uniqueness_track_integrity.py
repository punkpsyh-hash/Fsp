"""Атомарная связь ФСП ID и историческая добросовестность треков."""
from alembic import op
import sqlalchemy as sa

revision = 'f4b9d2e17a63'
down_revision = 'e8a1c4d27f03'
branch_labels = None
depends_on = None

CONSTRAINT = 'uq_profiles_fsp_member_id'


def upgrade():
    bind = op.get_bind()
    duplicate = bind.execute(sa.text(
        "SELECT 1 FROM profiles WHERE fsp_member_id IS NOT NULL "
        "GROUP BY fsp_member_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError(
            "Cannot enforce unique FSP identity links: duplicate links exist; "
            "owner data resolution is required before rerunning the migration."
        )

    op.add_column('confirmed_tracks', sa.Column('integrity_level', sa.String(length=20), nullable=True))
    bind.execute(sa.text(
        "UPDATE confirmed_tracks SET integrity_level = ("
        "SELECT profiles.integrity_level FROM profiles "
        "WHERE profiles.user_id = confirmed_tracks.user_id "
        "AND profiles.specialization = confirmed_tracks.specialization"
        ") WHERE EXISTS (SELECT 1 FROM profiles "
        "WHERE profiles.user_id = confirmed_tracks.user_id "
        "AND profiles.specialization = confirmed_tracks.specialization)"
    ))
    if bind.dialect.name == 'sqlite':
        with op.batch_alter_table('profiles') as batch:
            batch.create_unique_constraint(CONSTRAINT, ['fsp_member_id'])
    else:
        op.create_unique_constraint(CONSTRAINT, 'profiles', ['fsp_member_id'])


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        with op.batch_alter_table('profiles') as batch:
            batch.drop_constraint(CONSTRAINT, type_='unique')
        with op.batch_alter_table('confirmed_tracks') as batch:
            batch.drop_column('integrity_level')
    else:
        op.drop_constraint(CONSTRAINT, 'profiles', type_='unique')
        op.drop_column('confirmed_tracks', 'integrity_level')
