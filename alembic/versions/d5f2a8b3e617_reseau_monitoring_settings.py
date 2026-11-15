# ruff: noqa
"""reseau : réglages du suivi (intervalle par défaut, seuils du code couleur)

Revision ID: d5f2a8b3e617
Revises: c3e8f1a2d905
Create Date: 2026-11-15

"""
from alembic import op
import sqlalchemy as sa


revision = 'd5f2a8b3e617'
down_revision = 'c3e8f1a2d905'
branch_labels = None
depends_on = None

COLUMNS = ('default_check_interval', 'health_warn_intervals', 'health_red_failures', 'health_dark_red_seconds')


def upgrade() -> None:
    # Colonnes facultatives : NULL = valeur d'instance (variables GUIPAM_*).
    with op.batch_alter_table('reseau', schema=None) as batch_op:
        for name in COLUMNS:
            batch_op.add_column(sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('reseau', schema=None) as batch_op:
        for name in reversed(COLUMNS):
            batch_op.drop_column(name)
