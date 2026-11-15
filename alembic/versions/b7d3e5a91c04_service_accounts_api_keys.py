# ruff: noqa
"""comptes de service, clés d'API, traçabilité API dans l'audit

Revision ID: b7d3e5a91c04
Revises: f4a9c2d17b38
Create Date: 2026-11-15

Additif uniquement : deux nouvelles tables, trois colonnes nullable sur audit_log.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'b7d3e5a91c04'
down_revision = 'f4a9c2d17b38'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('service_account',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('role', sa.Enum('manager', 'user', name='role'), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('service_account', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_service_account_name'), ['name'], unique=True)

    op.create_table('api_key',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('service_account_id', sa.Integer(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('prefix', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('key_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('scope', sa.Enum('read', 'write', name='keyscope'), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.ForeignKeyConstraint(['service_account_id'], ['service_account.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('api_key', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_api_key_prefix'), ['prefix'], unique=True)
        batch_op.create_index(batch_op.f('ix_api_key_service_account_id'), ['service_account_id'], unique=False)

    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.add_column(sa.Column('service_account_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('api_key_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('api_key_label', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_column('api_key_label')
        batch_op.drop_column('api_key_id')
        batch_op.drop_column('service_account_id')

    with op.batch_alter_table('api_key', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_api_key_service_account_id'))
        batch_op.drop_index(batch_op.f('ix_api_key_prefix'))
    op.drop_table('api_key')

    with op.batch_alter_table('service_account', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_service_account_name'))
    op.drop_table('service_account')
