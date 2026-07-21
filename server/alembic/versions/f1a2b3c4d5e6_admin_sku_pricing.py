"""admin sku pricing

Revision ID: f1a2b3c4d5e6
Revises: f0a1b2c3d4e5
Create Date: 2026-07-21
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("role", sa.String(16), nullable=False, server_default="user"))
        batch_op.add_column(sa.Column("plan_sku_code", sa.String(64), nullable=False, server_default=""))
    op.create_index("ix_users_role", "users", ["role"])

    with op.batch_alter_table("activation_codes", schema=None) as batch_op:
        batch_op.alter_column("code", existing_type=sa.String(32), type_=sa.String(64), existing_nullable=False)
        batch_op.add_column(sa.Column("sku_version_id", sa.String(32), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("plan_sku_code", sa.String(64), nullable=False, server_default=""))
    op.create_index("ix_activation_codes_sku_version_id", "activation_codes", ["sku_version_id"])

    with op.batch_alter_table("activation_batches", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sku_version_id", sa.String(32), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("plan_sku_code", sa.String(64), nullable=False, server_default=""))
    op.create_index("ix_activation_batches_sku_version_id", "activation_batches", ["sku_version_id"])

    with op.batch_alter_table("user_subscriptions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sku_version_id", sa.String(32), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("plan_sku_code", sa.String(64), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("monthly_points", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("grants_issued", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("next_grant_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_user_subscriptions_next_grant_at", "user_subscriptions", ["next_grant_at"])

    op.create_table(
        "plan_skus",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_plan_skus_code", "plan_skus", ["code"], unique=True)

    op.create_table(
        "plan_sku_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("sku_id", sa.String(32), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("subtitle", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("badge", sa.String(32), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sku_type", sa.String(32), nullable=False, server_default="annual_bundle"),
        sa.Column("audience", sa.String(16), nullable=False, server_default="public"),
        sa.Column("duration_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("monthly_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("one_time_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("list_price_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("display_price_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("entitlements_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("max_concurrency", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_resolution", sa.String(16), nullable=False, server_default="1080p"),
        sa.Column("purchase_instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(32), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_plan_sku_versions_sku_id", "plan_sku_versions", ["sku_id"])
    op.create_index("ix_plan_sku_versions_code", "plan_sku_versions", ["code"])
    op.create_index("ix_plan_sku_versions_status", "plan_sku_versions", ["status"])
    op.create_index("ix_plan_sku_versions_audience", "plan_sku_versions", ["audience"])

    op.create_table(
        "price_catalog_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.String(32), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_price_catalog_versions_version", "price_catalog_versions", ["version"], unique=True)
    op.create_index("ix_price_catalog_versions_status", "price_catalog_versions", ["status"])

    op.create_table(
        "module_prices",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("catalog_version_id", sa.String(32), nullable=False),
        sa.Column("module", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("billing_unit", sa.String(32), nullable=False),
        sa.Column("unit_size", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("points_per_unit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("minimum_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("public_description", sa.Text(), nullable=False, server_default=""),
        sa.Column("internal_cost_cents_per_unit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_margin_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("catalog_version_id", "module", name="uq_catalog_module"),
    )
    op.create_index("ix_module_prices_catalog_version_id", "module_prices", ["catalog_version_id"])
    op.create_index("ix_module_prices_module", "module_prices", ["module"])

    op.create_table(
        "price_quotes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("catalog_version_id", sa.String(32), nullable=False),
        sa.Column("price_version", sa.String(64), nullable=False),
        sa.Column("items_json", sa.Text(), nullable=False),
        sa.Column("estimated_points", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="quoted"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_price_quotes_user_id", "price_quotes", ["user_id"])
    op.create_index("ix_price_quotes_catalog_version_id", "price_quotes", ["catalog_version_id"])
    op.create_index("ix_price_quotes_status", "price_quotes", ["status"])
    op.create_index("ix_price_quotes_expires_at", "price_quotes", ["expires_at"])

    op.create_table(
        "credit_reservations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("quote_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False, server_default=""),
        sa.Column("reserved_points", sa.Integer(), nullable=False),
        sa.Column("actual_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("allocations_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="reserved"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_credit_reservations_user_id", "credit_reservations", ["user_id"])
    op.create_index("ix_credit_reservations_quote_id", "credit_reservations", ["quote_id"])
    op.create_index("ix_credit_reservations_task_id", "credit_reservations", ["task_id"])
    op.create_index("ix_credit_reservations_status", "credit_reservations", ["status"])

    op.create_table(
        "credit_grants",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("granted_points", sa.Integer(), nullable=False),
        sa.Column("remaining_points", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_credit_grants_user_id", "credit_grants", ["user_id"])
    op.create_index("ix_credit_grants_source_type", "credit_grants", ["source_type"])
    op.create_index("ix_credit_grants_expires_at", "credit_grants", ["expires_at"])

    # 将升级前聚合余额转成可追溯的非过期积分批次；之后所有新积分都按 grant lot 管理。
    bind = op.get_bind()
    quota_accounts = sa.table(
        "quota_accounts",
        sa.column("user_id", sa.String(32)),
        sa.column("balance", sa.Float()),
    )
    credit_grants = sa.table(
        "credit_grants",
        sa.column("id", sa.String(32)),
        sa.column("user_id", sa.String(32)),
        sa.column("source_type", sa.String(24)),
        sa.column("source_id", sa.String(64)),
        sa.column("granted_points", sa.Integer()),
        sa.column("remaining_points", sa.Integer()),
        sa.column("expires_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    for row in bind.execute(sa.select(quota_accounts.c.user_id, quota_accounts.c.balance)):
        points = int(round(float(row.balance or 0)))
        if points <= 0:
            continue
        bind.execute(
            credit_grants.insert().values(
                id=uuid.uuid4().hex,
                user_id=row.user_id,
                source_type="legacy_migration",
                source_id="f1a2b3c4d5e6",
                granted_points=points,
                remaining_points=points,
                expires_at=None,
                created_at=datetime.now(UTC),
            )
        )

    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("points_delta", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(24), nullable=False, server_default=""),
        sa.Column("reference_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("price_version", sa.String(64), nullable=False, server_default=""),
        sa.Column("task_id", sa.String(32), nullable=False, server_default=""),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(32), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_credit_ledger_user_id", "credit_ledger", ["user_id"])
    op.create_index("ix_credit_ledger_event_type", "credit_ledger", ["event_type"])
    op.create_index("ix_credit_ledger_reference_id", "credit_ledger", ["reference_id"])
    op.create_index("ix_credit_ledger_task_id", "credit_ledger", ["task_id"])

    with op.batch_alter_table("pipeline_tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reservation_id", sa.String(32), nullable=False, server_default=""))
    op.create_index("ix_pipeline_tasks_reservation_id", "pipeline_tasks", ["reservation_id"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_tasks_reservation_id", table_name="pipeline_tasks")
    with op.batch_alter_table("pipeline_tasks", schema=None) as batch_op:
        batch_op.drop_column("reservation_id")

    op.drop_index("ix_credit_ledger_task_id", table_name="credit_ledger")
    op.drop_index("ix_credit_ledger_reference_id", table_name="credit_ledger")
    op.drop_index("ix_credit_ledger_event_type", table_name="credit_ledger")
    op.drop_index("ix_credit_ledger_user_id", table_name="credit_ledger")
    op.drop_table("credit_ledger")

    op.drop_index("ix_credit_grants_expires_at", table_name="credit_grants")
    op.drop_index("ix_credit_grants_source_type", table_name="credit_grants")
    op.drop_index("ix_credit_grants_user_id", table_name="credit_grants")
    op.drop_table("credit_grants")

    op.drop_index("ix_credit_reservations_status", table_name="credit_reservations")
    op.drop_index("ix_credit_reservations_task_id", table_name="credit_reservations")
    op.drop_index("ix_credit_reservations_quote_id", table_name="credit_reservations")
    op.drop_index("ix_credit_reservations_user_id", table_name="credit_reservations")
    op.drop_table("credit_reservations")

    op.drop_index("ix_price_quotes_expires_at", table_name="price_quotes")
    op.drop_index("ix_price_quotes_status", table_name="price_quotes")
    op.drop_index("ix_price_quotes_catalog_version_id", table_name="price_quotes")
    op.drop_index("ix_price_quotes_user_id", table_name="price_quotes")
    op.drop_table("price_quotes")

    op.drop_index("ix_module_prices_module", table_name="module_prices")
    op.drop_index("ix_module_prices_catalog_version_id", table_name="module_prices")
    op.drop_table("module_prices")

    op.drop_index("ix_price_catalog_versions_status", table_name="price_catalog_versions")
    op.drop_index("ix_price_catalog_versions_version", table_name="price_catalog_versions")
    op.drop_table("price_catalog_versions")

    op.drop_index("ix_plan_sku_versions_audience", table_name="plan_sku_versions")
    op.drop_index("ix_plan_sku_versions_status", table_name="plan_sku_versions")
    op.drop_index("ix_plan_sku_versions_code", table_name="plan_sku_versions")
    op.drop_index("ix_plan_sku_versions_sku_id", table_name="plan_sku_versions")
    op.drop_table("plan_sku_versions")

    op.drop_index("ix_plan_skus_code", table_name="plan_skus")
    op.drop_table("plan_skus")

    op.drop_index("ix_user_subscriptions_next_grant_at", table_name="user_subscriptions")
    with op.batch_alter_table("user_subscriptions", schema=None) as batch_op:
        batch_op.drop_column("expires_at")
        batch_op.drop_column("next_grant_at")
        batch_op.drop_column("grants_issued")
        batch_op.drop_column("monthly_points")
        batch_op.drop_column("plan_sku_code")
        batch_op.drop_column("sku_version_id")
    op.drop_index("ix_activation_batches_sku_version_id", table_name="activation_batches")
    with op.batch_alter_table("activation_batches", schema=None) as batch_op:
        batch_op.drop_column("plan_sku_code")
        batch_op.drop_column("sku_version_id")
    op.drop_index("ix_activation_codes_sku_version_id", table_name="activation_codes")
    with op.batch_alter_table("activation_codes", schema=None) as batch_op:
        batch_op.drop_column("plan_sku_code")
        batch_op.drop_column("sku_version_id")
    op.drop_index("ix_users_role", table_name="users")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("plan_sku_code")
        batch_op.drop_column("role")
