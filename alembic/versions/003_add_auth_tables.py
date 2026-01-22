"""add auth tables

Revision ID: 003
Revises: 002
Create Date: 2026-01-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    # 创建 users 表
    op.execute("""
        CREATE TABLE users (
            user_id UUID PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            hashed_password VARCHAR(255) NOT NULL,
            full_name VARCHAR(100),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_superuser BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_login_at TIMESTAMPTZ
        )
    """)
    
    # 创建索引
    op.execute('CREATE INDEX idx_users_username ON users(username)')
    op.execute('CREATE INDEX idx_users_email ON users(email)')
    
    # 创建 api_keys 表
    op.execute("""
        CREATE TABLE api_keys (
            key_id UUID PRIMARY KEY,
            user_id UUID NOT NULL,
            key_name VARCHAR(100) NOT NULL,
            key_hash VARCHAR(255) UNIQUE NOT NULL,
            key_prefix VARCHAR(10) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            expires_at TIMESTAMPTZ,
            last_used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    
    # 创建索引
    op.execute('CREATE INDEX idx_api_keys_user_id ON api_keys(user_id)')
    op.execute('CREATE INDEX idx_api_keys_key_hash ON api_keys(key_hash)')
    
    # 更新 documents 表，添加外键约束（可选，如果需要严格的数据完整性）
    # op.execute('ALTER TABLE documents ADD CONSTRAINT fk_documents_user FOREIGN KEY (user_id) REFERENCES users(user_id)')


def downgrade():
    # 删除表
    op.execute('DROP TABLE IF EXISTS api_keys')
    op.execute('DROP TABLE IF EXISTS users')
