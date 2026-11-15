# ruff: noqa
"""ip_address : pause volontaire (paused_at, pause_reason, pause_until, pause_until_recovery)

Revision ID: c3e8f1a2d905
Revises: b7d3e5a91c04
Create Date: 2026-11-15

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'c3e8f1a2d905'
down_revision = 'b7d3e5a91c04'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('ip_address', schema=None) as batch_op:
        batch_op.add_column(sa.Column('paused_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('pause_reason', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('pause_until', sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column('pause_until_recovery', sa.Boolean(), nullable=False, server_default=sa.text('0'))
        )


def downgrade() -> None:
    with op.batch_alter_table('ip_address', schema=None) as batch_op:
        batch_op.drop_column('pause_until_recovery')
        batch_op.drop_column('pause_until')
        batch_op.drop_column('pause_reason')
        batch_op.drop_column('paused_at')
