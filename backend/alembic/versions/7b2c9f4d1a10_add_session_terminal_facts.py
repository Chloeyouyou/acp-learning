"""add terminal facts and correction reopen count"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b2c9f4d1a10"
down_revision: Union[str, None] = "d8a4d2cf8080"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tutor_sessions") as batch_op:
        batch_op.add_column(sa.Column("completion_reason", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("terminal_actor", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("reopen_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("last_strategy_route", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tutor_sessions") as batch_op:
        batch_op.drop_column("reopen_count")
        batch_op.drop_column("last_strategy_route")
        batch_op.drop_column("completed_at")
        batch_op.drop_column("terminal_actor")
        batch_op.drop_column("completion_reason")
