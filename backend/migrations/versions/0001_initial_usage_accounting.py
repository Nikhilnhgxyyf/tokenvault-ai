"""Initial tables: tenants, model_prices, usage_events.

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    op.create_table(
        "model_prices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("input_micro_usd_per_million", sa.BigInteger(), nullable=False),
        sa.Column("output_micro_usd_per_million", sa.BigInteger(), nullable=False),
        sa.Column("cached_input_micro_usd_per_million", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("price_version", sa.String(length=64), nullable=False),
        sa.Column("price_source", sa.String(length=500), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "model", "price_version", name="uq_model_prices_provider_model_version"
        ),
        sa.CheckConstraint(
            "input_micro_usd_per_million >= 0 AND output_micro_usd_per_million >= 0 "
            "AND (cached_input_micro_usd_per_million IS NULL "
            "OR cached_input_micro_usd_per_million >= 0)",
            name="ck_model_prices_nonnegative",
        ),
    )
    op.create_index(
        "ix_model_prices_lookup", "model_prices", ["provider", "model", "effective_from"]
    )

    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("usage_origin", sa.String(length=32), nullable=False),
        sa.Column("price_id", sa.Integer(), nullable=True),
        sa.Column("price_version", sa.String(length=64), nullable=True),
        sa.Column("price_source", sa.String(length=500), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("estimated_cost_nano_usd", sa.BigInteger(), nullable=True),
        sa.Column("cost_status", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_usage_events_tenant_id_tenants"
        ),
        sa.ForeignKeyConstraint(
            ["price_id"], ["model_prices.id"], name="fk_usage_events_price_id_model_prices"
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0 AND completion_tokens >= 0 "
            "AND cached_prompt_tokens >= 0 AND total_tokens >= 0",
            name="ck_usage_events_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "cached_prompt_tokens <= prompt_tokens",
            name="ck_usage_events_cached_within_prompt",
        ),
        sa.CheckConstraint(
            "usage_origin IN ('provider_reported', 'simulated')",
            name="ck_usage_events_usage_origin",
        ),
        sa.CheckConstraint(
            "cost_status IN ('estimated', 'simulated', 'unavailable')",
            name="ck_usage_events_cost_status",
        ),
        sa.CheckConstraint(
            "(cost_status = 'unavailable' AND estimated_cost_nano_usd IS NULL) "
            "OR (cost_status <> 'unavailable' AND estimated_cost_nano_usd IS NOT NULL)",
            name="ck_usage_events_cost_consistency",
        ),
    )
    op.create_index(
        "ix_usage_events_tenant_occurred", "usage_events", ["tenant_id", "occurred_at"]
    )
    op.create_index(
        "ix_usage_events_tenant_request", "usage_events", ["tenant_id", "request_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_usage_events_tenant_request", table_name="usage_events")
    op.drop_index("ix_usage_events_tenant_occurred", table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_index("ix_model_prices_lookup", table_name="model_prices")
    op.drop_table("model_prices")
    op.drop_table("tenants")
  
