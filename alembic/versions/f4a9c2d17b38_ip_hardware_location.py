# ruff: noqa
"""ip_address : colonnes hardware et location

Revision ID: f4a9c2d17b38
Revises: 8a68124c8405
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'f4a9c2d17b38'
down_revision = '8a68124c8405'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('ip_address', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hardware', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('location', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ip_address', schema=None) as batch_op:
        batch_op.drop_column('location')
        batch_op.drop_column('hardware')
