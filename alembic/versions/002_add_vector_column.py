"""add vector column to block_versions

Revision ID: 002
Revises: 001
Create Date: 2026-01-22

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    # 1. 启用 pgvector 扩展
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    
    # 2. 添加 embedding 列到 block_versions 表
    op.execute("""
        ALTER TABLE block_versions 
        ADD COLUMN embedding vector(1536)
    """)
    
    # 3. 创建 HNSW 索引（用于快速向量相似度搜索）
    op.execute("""
        CREATE INDEX idx_block_versions_embedding 
        ON block_versions 
        USING hnsw (embedding vector_cosine_ops)
    """)


def downgrade():
    # 删除索引
    op.execute('DROP INDEX IF EXISTS idx_block_versions_embedding')
    
    # 删除列
    op.execute('ALTER TABLE block_versions DROP COLUMN IF EXISTS embedding')
    
    # 删除扩展（谨慎操作）
    # op.execute('DROP EXTENSION IF EXISTS vector')
