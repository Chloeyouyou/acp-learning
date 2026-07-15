"""add session_messages.meta

Revision ID: e4a9c7d21f30
Revises: cb5c7560d08f
Create Date: 2026-07-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4a9c7d21f30"
down_revision: Union[str, None] = "cb5c7560d08f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite 对既有表增加 NOT NULL JSON 列需要 server_default，确保旧行也是合法空对象。
    with op.batch_alter_table("session_messages") as batch_op:
        batch_op.add_column(sa.Column(
            "meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'"),
        ))


def downgrade() -> None:
    with op.batch_alter_table("session_messages") as batch_op:
        batch_op.drop_column("meta")
