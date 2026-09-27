"""scheduler run timestamp and notifications

Revision ID: 0002_scheduler_notifications
Revises: 0001_initial
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_scheduler_notifications"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "queued_at" not in {column["name"] for column in inspector.get_columns("backup_runs")}:
        op.add_column("backup_runs", sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False))
        op.create_index("ix_backup_runs_queued_at", "backup_runs", ["queued_at"])
    if "notification_targets" not in inspector.get_table_names():
        op.create_table(
            "notification_targets",
            sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("name", sa.String(length=200), nullable=False, unique=True), sa.Column("kind", sa.String(length=32), nullable=False), sa.Column("encrypted_config", sa.Text(), nullable=False), sa.Column("events", sa.JSON(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
    if "notification_deliveries" not in inspector.get_table_names():
        op.create_table(
            "notification_deliveries",
            sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("target_id", sa.Uuid(), sa.ForeignKey("notification_targets.id"), nullable=False), sa.Column("event", sa.String(length=100), nullable=False), sa.Column("status", sa.String(length=24), nullable=False), sa.Column("detail", sa.String(length=200), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    op.drop_table("notification_targets")
    op.drop_index("ix_backup_runs_queued_at", table_name="backup_runs")
    op.drop_column("backup_runs", "queued_at")
