from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.schemas import BlockCandidate, ScopeHint
from app.models import database as db_models
from app.utils.markdown import normalize_text
import uuid


class HybridRetriever:
    """混合检索器（BM25 + 向量检索）"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def search(
        self,
        query: str,
        doc_id: str,
        rev_id: str,
        scope_hint: Optional[ScopeHint] = None,
        top_k: int = 10
    ) -> List[BlockCandidate]:
        """
        混合检索
        MVP 阶段：使用简单的文本匹配
        """
        doc_uuid = uuid.UUID(doc_id)
        rev_uuid = uuid.UUID(rev_id)
        
        # 获取所有块
        blocks_query = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == rev_uuid
        )
        
        # 应用 scope_hint 过滤
        if scope_hint:
            if scope_hint.block_type:
                blocks_query = blocks_query.filter(
                    db_models.BlockVersion.block_type == scope_hint.block_type
                )
        
        blocks = blocks_query.order_by(db_models.BlockVersion.order_index).all()
        
        # 简单的关键词匹配评分
        candidates = []
        query_normalized = normalize_text(query)
        query_keywords = set(query_normalized.split())
        
        for block in blocks:
            # 计算相关性分数
            block_normalized = normalize_text(block.plain_text)
            block_keywords = set(block_normalized.split())
            
            # 计算关键词重叠度
            overlap = len(query_keywords & block_keywords)
            score = overlap / max(len(query_keywords), 1)
            
            # 如果有 heading 提示，增加权重
            if scope_hint and scope_hint.heading:
                # 获取父级 heading
                parent_heading = self._get_parent_heading(block)
                if parent_heading and scope_hint.heading.lower() in parent_heading.lower():
                    score += 0.3
            
            # 如果有关键词提示，检查是否包含
            if scope_hint and scope_hint.keywords:
                for keyword in scope_hint.keywords:
                    if normalize_text(keyword) in block_normalized:
                        score += 0.2
            
            if score > 0:
                candidates.append(BlockCandidate(
                    block_id=str(block.block_id),
                    snippet=block.plain_text[:200],
                    heading_context=self._get_parent_heading(block) or "（无标题）",
                    order_index=block.order_index,
                    score=min(score, 1.0),
                    block_type=block.block_type
                ))
        
        # 按分数排序
        candidates.sort(key=lambda x: x.score, reverse=True)
        
        return candidates[:top_k]
    
    def _get_parent_heading(self, block: db_models.BlockVersion) -> Optional[str]:
        """获取父级标题"""
        if not block.parent_heading_block_id:
            return None
        
        parent_block = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.block_id == block.parent_heading_block_id,
            db_models.BlockVersion.rev_id == block.rev_id
        ).first()
        
        if parent_block:
            return parent_block.plain_text
        
        return None
