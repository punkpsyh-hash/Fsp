"""Фиксация поддерживаемых прежних форм без изменения ответов и результатов."""
from alembic import op
import sqlalchemy as sa

revision='d795a01be238'
down_revision='c683e90a12d4'
branch_labels=None
depends_on=None


def upgrade():
    from src.server.assessment import questions
    bind=op.get_bind()
    attempts=sa.table('attempts',sa.column('id',sa.String),sa.column('question_form',sa.JSON))
    rows=bind.execute(sa.text('SELECT id,seed,grade,specialization,blueprint_version FROM attempts WHERE question_form IS NULL')).mappings().all()
    for row in rows:
        if row['blueprint_version'] not in ('families-v3','families-v2','demo-backend-v1'): continue
        form=questions(row['seed'],row['grade'],row['specialization'],row['blueprint_version'])
        bind.execute(attempts.update().where(attempts.c.id==row['id']).values(question_form=form))


def downgrade():
    # Фиксация формы не должна терять данные при откате схемы.
    pass
