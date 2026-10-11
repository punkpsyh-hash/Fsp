"""Сообщения между компанией и кандидатом после открытия контакта."""
from alembic import op
import sqlalchemy as sa

revision = 'a9c4e7d12b58'
down_revision = 'f4b9d2e17a63'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('chat_messages',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('company_id', sa.String(64), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('candidate_id', sa.String(64), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('sender_role', sa.String(10), nullable=False),
        sa.Column('body', sa.String(2000), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_chat_messages_company_id', 'chat_messages', ['company_id'])
    op.create_index('ix_chat_messages_candidate_id', 'chat_messages', ['candidate_id'])
    op.create_index('ix_chat_thread', 'chat_messages', ['company_id', 'candidate_id', 'created_at'])


def downgrade():
    op.drop_index('ix_chat_thread', table_name='chat_messages')
    op.drop_index('ix_chat_messages_candidate_id', table_name='chat_messages')
    op.drop_index('ix_chat_messages_company_id', table_name='chat_messages')
    op.drop_table('chat_messages')
