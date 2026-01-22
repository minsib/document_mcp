"""
批量发现节点 - 用于批量修改操作
"""
from typing import List, Set
from app.models.schemas import Intent, BlockCandidate
from app.services.search_indexer import get_indexer
from app.models import database as db_models
from sqlalchemy.orm import Session
import re


class BulkDiscoverNode:
    """批量发现节点 - 召回所有匹配的块"""
    
    def __init__(self, db: Session):
        self.db = db
        try:
            self.indexer = get_indexer()
        except:
            self.indexer = None
    
    def discover(
        self,
        intent: Intent,
        doc_id: str,
        rev_id: str,
        max_changes: int = 100
    ) -> List[BlockCandidate]:
        """
        批量发现匹配的块
        
        Args:
            intent: 用户意图
            doc_id: 文档 ID
            rev_id: 版本 ID
            max_changes: 最大修改数量限制
        
        Returns:
            匹配的块列表
        """
        # 构建查询
        if intent.match_type == "exact_term":
            # 精确词匹配
            query = intent.scope_filter.get("term", "")
        elif intent.match_type == "regex":
            # 正则表达式匹配（需要全量拉取后过滤）
            query = ""
        else:
            # 语义匹配
            query = " ".join(intent.scope_hint.keywords) if intent.scope_hint.keywords else ""
        
        # 召回候选
        if self.indexer and query:
            candidates = self._search_with_meilisearch(query, doc_id, rev_id)
        else:
            candidates = self._search_with_db(doc_id, rev_id)
        
        # 按 scope_filter 进一步过滤
        filtered = self._filter_by_scope(candidates, intent)
        
        # 限制最大影响范围
        if len(filtered) > max_changes:
            raise ValueError(
                f"将影响 {len(filtered)} 处，超过限制 {max_changes}，请缩小范围"
            )
        
        return filtered
    
    def _search_with_meilisearch(
        self,
        query: str,
        doc_id: str,
        rev_id: str
    ) -> List[BlockCandidate]:
        """使用 Meilisearch 搜索"""
        all_candidates = []
        offset = 0
        limit = 100
        
        while True:
            try:
                results = self.indexer.search(
                    query,
                    doc_id,
                    rev_id,
                    filters={},
                    limit=limit
                )
                
                if not results:
                    break
                
                # 转换为 BlockCandidate
                for result in results:
                    all_candidates.append(BlockCandidate(
                        block_id=result['block_id'],
                        snippet=result.get('plain_text', '')[:200],
                        heading_context=result.get('parent_heading_text', '（无标题）'),
                        order_index=result.get('order_index', 0),
                        score=1.0,
                        block_type=result.get('block_type', 'paragraph')
                    ))
                
                offset += limit
                
                # 安全限制：最多 1000 个候选
                if len(all_candidates) >= 1000:
                    break
                
                # 如果返回结果少于 limit，说明已经到底了
                if len(results) < limit:
                    break
                    
            except Exception as e:
                print(f"Meilisearch 搜索失败: {e}")
                break
        
        return all_candidates
    
    def _search_with_db(
        self,
        doc_id: str,
        rev_id: str
    ) -> List[BlockCandidate]:
        """使用数据库全量拉取"""
        import uuid
        
        rev_uuid = uuid.UUID(rev_id)
        
        blocks = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == rev_uuid
        ).order_by(db_models.BlockVersion.order_index).all()
        
        candidates = []
        for block in blocks:
            # 获取父级标题
            parent_heading = self._get_parent_heading(block)
            
            candidates.append(BlockCandidate(
                block_id=str(block.block_id),
                snippet=block.plain_text[:200] if block.plain_text else '',
                heading_context=parent_heading or "（无标题）",
                order_index=block.order_index,
                score=1.0,
                block_type=block.block_type
            ))
        
        return candidates
    
    def _filter_by_scope(
        self,
        candidates: List[BlockCandidate],
        intent: Intent
    ) -> List[BlockCandidate]:
        """按 scope_filter 过滤"""
        filtered = candidates
        
        # 按 block_type 过滤
        if intent.scope_hint and intent.scope_hint.block_type:
            filtered = [
                c for c in filtered 
                if c.block_type == intent.scope_hint.block_type
            ]
        
        # 按 heading 过滤
        if intent.scope_hint and intent.scope_hint.heading:
            heading_keyword = intent.scope_hint.heading.lower()
            filtered = [
                c for c in filtered 
                if heading_keyword in c.heading_context.lower()
            ]
        
        # 按 regex 过滤
        if intent.match_type == "regex" and intent.scope_filter:
            pattern_str = intent.scope_filter.get("pattern", "")
            if pattern_str:
                try:
                    pattern = re.compile(pattern_str)
                    filtered = [
                        c for c in filtered 
                        if pattern.search(c.snippet)
                    ]
                except re.error as e:
                    print(f"正则表达式错误: {e}")
        
        # 按精确词过滤
        if intent.match_type == "exact_term" and intent.scope_filter:
            term = intent.scope_filter.get("term", "")
            if term:
                filtered = [
                    c for c in filtered 
                    if term in c.snippet
                ]
        
        return filtered
    
    def _get_parent_heading(self, block: db_models.BlockVersion) -> str:
        """获取父级标题"""
        if not block.parent_heading_block_id:
            return None
        
        parent = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.block_id == block.parent_heading_block_id,
            db_models.BlockVersion.rev_id == block.rev_id
        ).first()
        
        return parent.plain_text if parent else None
