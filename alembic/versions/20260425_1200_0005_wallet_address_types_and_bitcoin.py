"""add wallet address type metadata for parallel bitcoin/liquid flows

Revision ID: 20260425_1200_0005
Revises: 0004
Create Date: 2026-04-25 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260425_1200_0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _column_names(bind: sa.engine.Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _unique_constraint_columns(bind: sa.engine.Connection, table_name: str, constraint_name: str) -> tuple[str, ...] | None:
    inspector = sa.inspect(bind)
    for constraint in inspector.get_unique_constraints(table_name):
        if constraint.get("name") == constraint_name:
            return tuple(constraint.get("column_names") or ())
    return None


def upgrade() -> None:
    bind = op.get_bind()
    columns = _column_names(bind, "wallet_addresses")

    if "address_type" not in columns:
        op.add_column(
            "wallet_addresses",
            sa.Column("address_type", sa.String(length=32), nullable=False, server_default="liquid_confidential"),
        )
    if "network" not in columns:
        op.add_column(
            "wallet_addresses",
            sa.Column("network", sa.String(length=32), nullable=False, server_default="liquid"),
        )
    if "derivation_path" not in columns:
        op.add_column(
            "wallet_addresses",
            sa.Column("derivation_path", sa.String(length=64), nullable=True),
        )

    columns = _column_names(bind, "wallet_addresses")
    if {"address_type", "network"}.issubset(columns):
        op.execute(
            "UPDATE wallet_addresses "
            "SET network = 'elementsregtest' "
            "WHERE address_type = 'liquid_confidential' AND network = 'liquid'"
        )

    constraint_columns = _unique_constraint_columns(
        bind,
        "wallet_addresses",
        "uq_wallet_addresses_wallet_derivation",
    )
    desired_columns = ("wallet_id", "address_type", "network", "derivation_index")
    if constraint_columns != desired_columns:
        if constraint_columns is not None:
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
