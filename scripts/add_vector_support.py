#!/usr/bin/env python3
"""
添加向量搜索支持的脚本

运行此脚本将：
1. 启用 pgvector 扩展
2. 添加 embedding 列到 block_versions 表
3. 创建 HNSW 索引
"""
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.connection import get_db
from sqlalchemy import text


def add_vector_support():
    """添加向量搜索支持"""
    db = next(get_db())
    
    try:
        print("🔧 开始添加向量搜索支持...")
        
        # 1. 启用 pgvector 扩展
        print("1️⃣ 启用 pgvector 扩展...")
        db.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
        db.commit()
        print("✅ pgvector 扩展已启用")
        
        # 2. 检查列是否已存在
        check_column = text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'block_versions' 
            AND column_name = 'embedding'
        """)
        result = db.execute(check_column).fetchone()
        
        if result:
            print("⚠️ embedding 列已存在，跳过添加")
        else:
            # 添加 embedding 列
            print("2️⃣ 添加 embedding 列到 block_versions 表...")
            db.execute(text("""
                ALTER TABLE block_versions 
                ADD COLUMN embedding vector(1536)
            """))
            db.commit()
            print("✅ embedding 列已添加")
        
        # 3. 检查索引是否已存在
        check_index = text("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = 'block_versions' 
            AND indexname = 'idx_block_versions_embedding'
        """)
        result = db.execute(check_index).fetchone()
        
        if result:
            print("⚠️ HNSW 索引已存在，跳过创建")
        else:
            # 创建 HNSW 索引
            print("3️⃣ 创建 HNSW 索引（这可能需要几分钟）...")
            db.execute(text("""
                CREATE INDEX idx_block_versions_embedding 
                ON block_versions 
                USING hnsw (embedding vector_cosine_ops)
            """))
            db.commit()
            print("✅ HNSW 索引已创建")
        
        print("\n🎉 向量搜索支持添加完成！")
        print("\n📝 下一步：")
        print("   1. 重新索引现有文档以生成 embeddings")
        print("   2. 使用 HybridRetriever 进行混合检索")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    add_vector_support()
