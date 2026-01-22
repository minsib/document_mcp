"""
Meilisearch 索引管理 + Embedding 生成
"""
from typing import List, Set
import meilisearch
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models import database as db_models
from app.config import get_settings
from app.services.embedding import get_embedding_service
import uuid

settings = get_settings()


class MeilisearchIndexer:
    """Meilisearch 索引管理器 + Embedding 生成器"""
    
    def __init__(self):
        self.client = meilisearch.Client(
            settings.MEILI_HOST,
            settings.MEILI_MASTER_KEY
        )
        self.index_name = "doc_blocks"
        self.embedding_service = get_embedding_service()
        self._ensure_index()
    
    def _ensure_index(self):
        """确保索引存在并配置正确"""
        try:
            index = self.client.get_index(self.index_name)
        except:
            # 创建索引
            self.client.create_index(self.index_name, {'primaryKey': 'id'})
            index = self.client.get_index(self.index_name)
        
        # 配置索引
        index.update_filterable_attributes([
            'doc_id',
            'rev_id',
            'block_type',
            'heading_level',
            'char_count'
        ])
        
        index.update_sortable_attributes([
            'order_index',
            'created_at',
            'char_count'
        ])
        
        index.update_searchable_attributes([
            'plain_text',
            'parent_heading_text',
            'heading_path'
        ])
        
        index.update_ranking_rules([
            'words',
            'typo',
            'proximity',
            'attribute',
            'sort',
            'exactness'
        ])
    
    def index_document_blocks(self, doc_id: str, rev_id: str, db: Session):
        """索引文档的所有块 + 生成 embeddings"""
        doc_uuid = uuid.UUID(doc_id)
        rev_uuid = uuid.UUID(rev_id)
        
        # 获取所有块
        blocks = db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == rev_uuid
        ).order_by(db_models.BlockVersion.order_index).all()
        
        # 构建文档
        documents = []
        texts_for_embedding = []
        block_version_ids = []
        
        for block in blocks:
            # 获取父级标题
            parent_heading_text = self._get_parent_heading(block, db)
            heading_path = self._get_heading_path(block, db)
            
            doc = {
                'id': f"{block.block_id}_{rev_id}",
                'block_id': str(block.block_id),
                'doc_id': str(doc_id),
                'rev_id': str(rev_id),
                'order_index': block.order_index,
                'block_type': block.block_type,
                'heading_level': block.heading_level,
                'parent_heading_text': parent_heading_text or '',
                'heading_path': heading_path,
                'plain_text': block.plain_text or '',
                'content_md': block.content_md or '',
                'char_count': len(block.plain_text or ''),
                'created_at': int(block.created_at.timestamp()) if block.created_at else 0
            }
            documents.append(doc)
            
            # 准备 embedding 文本（包含标题上下文）
            embedding_text = f"{parent_heading_text or ''}\n\n{block.plain_text or ''}"
            texts_for_embedding.append(embedding_text)
            block_version_ids.append(block.block_version_id)
        
        # 批量索引到 Meilisearch
        if documents:
            index = self.client.get_index(self.index_name)
            index.add_documents(documents)
        
        # 批量生成 embeddings 并存储到数据库
        if texts_for_embedding:
            try:
                embeddings = self.embedding_service.generate_embeddings_batch(texts_for_embedding)
                
                # 批量更新数据库
                for block_version_id, embedding in zip(block_version_ids, embeddings):
                    # 将向量转换为字符串格式
                    embedding_str = '[' + ','.join(map(str, embedding)) + ']'
                    db.execute(
                        text("""
                            UPDATE block_versions 
                            SET embedding = :embedding::vector
                            WHERE block_version_id = :block_version_id::uuid
                        """),
                        {
                            'embedding': embedding_str,
                            'block_version_id': str(block_version_id)
                        }
                    )
                db.commit()
                print(f"✅ 成功生成并存储 {len(embeddings)} 个 embeddings")
            except Exception as e:
                print(f"⚠️ Embedding 生成失败（不影响主流程）: {e}")
                # 回滚失败的事务
                db.rollback()
                # 不抛出异常，允许继续
    
    def update_index_for_new_revision(
        self,
        doc_id: str,
        old_rev_id: str,
        new_rev_id: str,
        changed_block_ids: Set[uuid.UUID],
        db: Session
    ):
        """增量更新索引"""
        doc_uuid = uuid.UUID(doc_id)
        new_rev_uuid = uuid.UUID(new_rev_id)
        
        # 获取所有块数量
        total_blocks = db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == new_rev_uuid
        ).count()
        
        # 如果块数量少于 1000，直接全量重新索引
        if total_blocks < 1000:
            # 先删除旧索引
            self.delete_document_index(doc_id)
            # 重新索引
            self.index_document_blocks(doc_id, new_rev_id, db)
            return
        
        # 否则增量更新
        # 1. 索引变更的块
        changed_blocks = db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == new_rev_uuid,
            db_models.BlockVersion.block_id.in_(changed_block_ids)
        ).all()
        
        documents = []
        for block in changed_blocks:
            parent_heading_text = self._get_parent_heading(block, db)
            heading_path = self._get_heading_path(block, db)
            
            doc = {
                'id': f"{block.block_id}_{new_rev_id}",
                'block_id': str(block.block_id),
                'doc_id': str(doc_id),
                'rev_id': str(new_rev_id),
                'order_index': block.order_index,
                'block_type': block.block_type,
                'heading_level': block.heading_level,
                'parent_heading_text': parent_heading_text or '',
                'heading_path': heading_path,
                'plain_text': block.plain_text or '',
                'content_md': block.content_md or '',
                'char_count': len(block.plain_text or ''),
                'created_at': int(block.created_at.timestamp()) if block.created_at else 0
            }
            documents.append(doc)
        
        if documents:
            index = self.client.get_index(self.index_name)
            index.add_documents(documents)
        
        # 2. 复制未变更块的索引
        all_block_ids = {block.block_id for block in db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == new_rev_uuid
        ).all()}
        
        unchanged_block_ids = all_block_ids - changed_block_ids
        
        # 从旧索引复制
        for block_id in unchanged_block_ids:
            old_doc_id = f"{block_id}_{old_rev_id}"
            try:
                index = self.client.get_index(self.index_name)
                old_doc = index.get_document(old_doc_id)
                
                # 创建新文档
                new_doc = {
                    **old_doc,
                    'id': f"{block_id}_{new_rev_id}",
                    'rev_id': str(new_rev_id)
                }
                index.add_documents([new_doc])
            except:
                # 如果旧文档不存在，跳过
                pass
    
    def delete_document_index(self, doc_id: str):
        """删除文档的所有索引"""
        index = self.client.get_index(self.index_name)
        index.delete_documents({'filter': f'doc_id = {doc_id}'})
    
    def search(
        self,
        query: str,
        doc_id: str,
        rev_id: str,
        filters: dict = None,
        limit: int = 20
    ) -> List[dict]:
        """搜索"""
        index = self.client.get_index(self.index_name)
        
        # 构建过滤器
        filter_str = f'doc_id = {doc_id} AND rev_id = {rev_id}'
        if filters:
            if filters.get('block_type'):
                filter_str += f' AND block_type = {filters["block_type"]}'
            if filters.get('heading_level'):
                filter_str += f' AND heading_level = {filters["heading_level"]}'
        
        # 搜索
        results = index.search(
            query,
            {
                'filter': filter_str,
                'limit': limit,
                'attributesToRetrieve': ['*']
            }
        )
        
        return results['hits']
    
    def _get_parent_heading(self, block: db_models.BlockVersion, db: Session) -> str:
        """获取父级标题"""
        if not block.parent_heading_block_id:
            return None
        
        parent = db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.block_id == block.parent_heading_block_id,
            db_models.BlockVersion.rev_id == block.rev_id
        ).first()
        
        return parent.plain_text if parent else None
    
    def _get_heading_path(self, block: db_models.BlockVersion, db: Session) -> List[str]:
        """获取标题路径"""
        path = []
        current_block = block
        
        while current_block and current_block.parent_heading_block_id:
            parent = db.query(db_models.BlockVersion).filter(
                db_models.BlockVersion.block_id == current_block.parent_heading_block_id,
                db_models.BlockVersion.rev_id == current_block.rev_id
            ).first()
            
            if parent:
                path.insert(0, parent.plain_text)
                current_block = parent
            else:
                break
        
        return path


# 全局实例
_indexer = None


def get_indexer() -> MeilisearchIndexer:
    """获取索引器单例"""
    global _indexer
    if _indexer is None:
        _indexer = MeilisearchIndexer()
    return _indexer
