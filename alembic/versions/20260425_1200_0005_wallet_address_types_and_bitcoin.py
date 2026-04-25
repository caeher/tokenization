"""add wallet address type metadata for parallel bitcoin/liquid flows

Revision ID: 20260425_1200_0005
Revises: 20260424_1415_0004
Create Date: 2026-04-25 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260425_1200_0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wallet_addresses",
        sa.Column("address_type", sa.String(length=32), nullable=False, server_default="liquid_confidential"),
    )
    op.add_column(
        "wallet_addresses",
        sa.Column("network", sa.String(length=32), nullable=False, server_default="liquid"),
    )
    op.add_column(
        "wallet_addresses",
        sa.Column("derivation_path", sa.String(length=64), nullable=True),
    )
    op.execute(
        "UPDATE wallet_addresses "
        "SET network = 'elementsregtest' "
        "WHERE address_type = 'liquid_confidential' AND network = 'liquid'"
    )
    op.drop_constraint("uq_wallet_addresses_wallet_derivation", "wallet_addresses", type_="unique")
    op.create_unique_constraint(
        "uq_wallet_addresses_wallet_derivation",
        "wallet_addresses",
        ["wallet_id", "address_type", "network", "derivation_index"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_wallet_addresses_wallet_derivation", "wallet_addresses", type_="unique")
    op.create_unique_constraint(
        "uq_wallet_addresses_wallet_derivation",
        "wallet_addresses",
        ["wallet_id", "derivation_index"],
    )
    op.drop_column("wallet_addresses", "derivation_path")
    op.drop_column("wallet_addresses", "network")
    op.drop_column("wallet_addresses", "address_type")
