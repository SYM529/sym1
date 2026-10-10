"""审计日志表

配合 server/database.py 的 AuditLog 模型。
已有库执行 `alembic upgrade head` 即可（只会新增这张表，不影响 users）。

String 长度必须显式：MySQL 的 VARCHAR 不给长度无法建表（SQLite 会忽略长度），
长度与 server/database.py 的 AuditLog 对齐。
"""

from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("ts", sa.DateTime(), nullable=True, index=True),
        sa.Column("actor", sa.String(64), nullable=True, index=True),
        sa.Column("action", sa.String(32), nullable=True, index=True),
        sa.Column("target", sa.String(255), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=True),
        sa.Column("detail", sa.String(500), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
