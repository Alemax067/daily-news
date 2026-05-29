"""timeline: fetch_tasks.run_id + news_items.fetch_task_id

Revision ID: d2a8b1e4c317
Revises: 11a6f542a31b
Create Date: 2026-05-29 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2a8b1e4c317"
down_revision: Union[str, None] = "11a6f542a31b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("fetch_tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("run_id", sa.String(length=36), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_fetch_tasks_run_id"), ["run_id"], unique=False
        )

    with op.batch_alter_table("news_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fetch_task_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_news_items_fetch_task_id",
            "fetch_tasks",
            ["fetch_task_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            batch_op.f("ix_news_items_fetch_task_id"),
            ["fetch_task_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("news_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_news_items_fetch_task_id"))
        batch_op.drop_constraint("fk_news_items_fetch_task_id", type_="foreignkey")
        batch_op.drop_column("fetch_task_id")

    with op.batch_alter_table("fetch_tasks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_fetch_tasks_run_id"))
        batch_op.drop_column("run_id")
