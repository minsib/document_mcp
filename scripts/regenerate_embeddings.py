#!/usr/bin/env python3
"""
为现有文档重新生成 embeddings

用法:
    python scripts/regenerate_embeddings.py [doc_id]
    
    如果不指定 doc_id，将为所有文档生成 embeddings
"""
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.connection import get_db
from app.models import database as db_models
from app.services.embedding import get_embedding_service
from sqlalchemy import text
import uuid


def regenerate_embeddings(doc_id: str = None):
    """重新生成 embeddings"""
    db = next(get_db())
    embedding_service = get_embedding_service()
    
    try:
        # 获取需要处理的文档
        if doc_id:
            docs = db.query(db_models.Document).filter(
                db_models.Document.doc_id == uuid.UUID(doc_id)
            ).all()
            if not docs:
                print(f"❌ 文档 {doc_id} 不存在")
                return
        else:
            docs = db.query(db_models.Document).all()
        
        print(f"📚 找到 {len(docs)} 个文档需要处理")
        
        for doc in docs:
            print(f"\n🔄 处理文档: {doc.title} ({doc.doc_id})")
            
            # 获取当前活跃版本
            active_rev = db.query(db_models.DocumentActiveRevision).filter(
                db_models.DocumentActiveRevision.doc_id == doc.doc_id
            ).first()
            
            if not active_rev:
                print(f"⚠️ 文档 {doc.doc_id} 没有活跃版本，跳过")
                continue
            
            # 获取所有块
            blocks = db.query(db_models.BlockVersion).filter(
                db_models.BlockVersion.rev_id == active_rev.rev_id
            ).order_by(db_models.BlockVersion.order_index).all()
            
            print(f"   找到 {len(blocks)} 个块")
            
            # 准备文本
            texts_for_embedding = []
            block_version_ids = []
            
            for block in blocks:
                # 获取父级标题
                parent_heading_text = ""
                if block.parent_heading_block_id:
                    parent = db.query(db_models.BlockVersion).filter(
                        db_models.BlockVersion.block_id == block.parent_heading_block_id,
                        db_models.BlockVersion.rev_id == block.rev_id
                    ).first()
                    if parent:
                        parent_heading_text = parent.plain_text or ""
                
                # 组合文本（包含标题上下文）
                embedding_text = f"{parent_heading_text}\n\n{block.plain_text or ''}"
                texts_for_embedding.append(embedding_text)
                block_version_ids.append(block.block_version_id)
            
            # 批量生成 embeddings
            print(f"   🤖 生成 embeddings...")
            embeddings = embedding_service.generate_embeddings_batch(texts_for_embedding)
            
            # 批量更新数据库
            print(f"   💾 保存到数据库...")
            for block_version_id, embedding in zip(block_version_ids, embeddings):
                db.execute(
                    text("""
                        UPDATE block_versions 
                        SET embedding = :embedding::vector
                        WHERE block_version_id = :block_version_id
                    """),
                    {
                        'embedding': str(embedding),
                        'block_version_id': block_version_id
                    }
                )
            
            db.commit()
            print(f"   ✅ 完成 {len(embeddings)} 个 embeddings")
        
        print(f"\n🎉 所有文档处理完成！")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    doc_id = sys.argv[1] if len(sys.argv) > 1 else None
    regenerate_embeddings(doc_id)
