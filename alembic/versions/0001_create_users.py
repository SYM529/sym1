"""初始 schema：users 表

由手工编写而非 autogenerate：我们希望迁移文件可读、可审计，
并且明确知道每一步在做什么（SQLite 对 ALTER 的支持有限，
字段补齐在生产库上必须显式声明）。

注：is_admin / password_version 是后续迭代加入的，
为了让**全新部署**一步到位，这里直接建出最终形态。
已存在的旧库用 `alembic stamp 0001` 标记为已迁移即可。
"""

from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("username", sa.String(), nullable=False, index=True, unique=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column(
            "is_admin", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "password_version", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_table("users")
