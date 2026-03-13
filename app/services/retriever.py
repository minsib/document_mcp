from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models.schemas import BlockCandidate, ScopeHint
from app.models import database as db_models
from app.utils.markdown import normalize_text
from app.utils.intent_helper import get_intent_attr
from app.services.search_indexer import get_indexer
from app.services.embedding import get_embedding_service
from app.monitoring.metrics import (
    meilisearch_query_duration,
    retrieval_duration,
    retrieval_requests,
    search_results_count,
    searches_performed,
    vector_search_duration,
)
import time
import uuid


class HybridRetriever:
    """混合检索器（BM25 + 向量检索 + RRF 融合）"""
    
    def __init__(self, db: Session, use_meilisearch: bool = True, use_vector: bool = True):
        self.db = db
        self.use_meilisearch = use_meilisearch
        self.use_vector = use_vector
        
        if use_meilisearch:
            try:
                self.indexer = get_indexer()
            except:
                self.use_meilisearch = False
                self.indexer = None
        else:
            self.indexer = None
        
        if use_vector:
            try:
                self.embedding_service = get_embedding_service()
            except:
                self.use_vector = False
                self.embedding_service = None
        else:
            self.embedding_service = None
    
    def search(
        self,
        query: str,
        doc_id: str,
        rev_id: str,
        scope_hint: Optional[ScopeHint] = None,
        top_k: int = 10
    ) -> List[BlockCandidate]:
        """
        混合检索（BM25 + 向量 + RRF 融合）
        优先使用混合检索，失败则降级
        """
        search_start = time.time()

        # 尝试混合检索（BM25 + 向量）
        if self.use_meilisearch and self.use_vector and self.indexer and self.embedding_service:
            try:
                results = self._hybrid_search(query, doc_id, rev_id, scope_hint, top_k)
                if results:
                    searches_performed.labels(search_type="hybrid", status="success").inc()
                    search_results_count.observe(len(results))
                    retrieval_duration.labels(mode="hybrid").observe(time.time() - search_start)
                    retrieval_requests.labels(mode="hybrid", status="success").inc()
                    return results
                searches_performed.labels(search_type="hybrid", status="empty").inc()
                print("混合检索返回空结果，尝试 Meilisearch 搜索")
            except Exception as e:
                searches_performed.labels(search_type="hybrid", status="error").inc()
                print(f"混合检索失败: {e}")
        
        # 降级到 Meilisearch
        if self.use_meilisearch and self.indexer:
            try:
                results = self._meilisearch_search(query, doc_id, rev_id, scope_hint, top_k)
                if results:
                    searches_performed.labels(search_type="meilisearch", status="success").inc()
                    search_results_count.observe(len(results))
                    retrieval_duration.labels(mode="meilisearch").observe(time.time() - search_start)
                    retrieval_requests.labels(mode="meilisearch", status="success").inc()
                    return results
                searches_performed.labels(search_type="meilisearch", status="empty").inc()
                print("Meilisearch 返回空结果，尝试简单搜索")
            except Exception as e:
                searches_performed.labels(search_type="meilisearch", status="error").inc()
                print(f"Meilisearch 搜索失败，降级到简单匹配: {e}")
        
        # 最终降级到简单搜索
        try:
            results = self._simple_search(query, doc_id, rev_id, scope_hint, top_k)
            final_status = "success" if results else "empty"
            searches_performed.labels(search_type="simple", status=final_status).inc()
            search_results_count.observe(len(results))
            retrieval_duration.labels(mode="simple").observe(time.time() - search_start)
            retrieval_requests.labels(mode="simple", status=final_status).inc()
            return results
        except Exception:
            searches_performed.labels(search_type="simple", status="error").inc()
            retrieval_duration.labels(mode="simple").observe(time.time() - search_start)
            retrieval_requests.labels(mode="simple", status="error").inc()
            return []
    
    def _hybrid_search(
        self,
        query: str,
        doc_id: str,
        rev_id: str,
        scope_hint: Optional[ScopeHint],
        top_k: int
    ) -> List[BlockCandidate]:
        """混合检索：BM25 + 向量 + RRF 融合"""
        # 1. BM25 召回
        bm25_results = self._meilisearch_search(query, doc_id, rev_id, scope_hint, top_k * 2)
        
        # 2. 向量召回
        vector_results = self._vector_search(query, doc_id, rev_id, scope_hint, top_k * 2)
        
        # 3. RRF 融合
        combined = self._reciprocal_rank_fusion(
            [bm25_results, vector_results],
            k=60
        )
        
        return combined[:top_k]
    
    def _vector_search(
        self,
        query: str,
        doc_id: str,
        rev_id: str,
        scope_hint: Optional[ScopeHint],
        top_k: int
    ) -> List[BlockCandidate]:
        """向量相似度搜索"""
        start_time = time.time()
        try:
            # 生成查询向量
            query_embedding = self.embedding_service.generate_embedding(query)
            
            # 构建 SQL 查询
            rev_uuid = uuid.UUID(rev_id)
            
            # 将向量转换为字符串格式
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
            
            # 使用余弦距离搜索 - 使用 format 构建 SQL
            sql_query = f"""
                SELECT 
                    bv.block_id,
                    bv.plain_text,
                    bv.order_index,
                    bv.block_type,
                    bv.embedding <=> '{embedding_str}'::vector AS distance
                FROM block_versions bv
                WHERE bv.rev_id = '{str(rev_uuid)}'::uuid
                    AND bv.embedding IS NOT NULL
                ORDER BY distance
                LIMIT {top_k}
            """
            
            results = self.db.execute(text(sql_query)).fetchall()
            
            # 转换为 BlockCandidate
            candidates = []
            for row in results:
                # 距离转换为分数（0-1）
                score = 1.0 / (1.0 + row.distance)
                
                # 获取父级标题
                parent_heading = self._get_parent_heading_by_id(str(row.block_id), rev_id)
                
                # 应用 scope_hint 加权
                if scope_hint:
                    heading = None
                    if isinstance(scope_hint, dict):
                        heading = scope_hint.get("heading")
                    else:
                        heading = getattr(scope_hint, "heading", None)
                    
                    if heading and parent_heading:
                        if heading.lower() in parent_heading.lower():
                            score += 0.3
                    
                    keywords = []
                    if isinstance(scope_hint, dict):
                        keywords = scope_hint.get("keywords", [])
                    else:
                        keywords = getattr(scope_hint, "keywords", [])
                    
                    for keyword in keywords:
                        if normalize_text(keyword) in normalize_text(row.plain_text):
                            score += 0.2
                
                candidates.append(BlockCandidate(
                    block_id=str(row.block_id),
                    snippet=row.plain_text[:200] if row.plain_text else '',
                    heading_context=parent_heading or "（无标题）",
                    order_index=row.order_index,
                    score=min(score, 1.0),
                    block_type=row.block_type
                ))
            
            return candidates
            
        except Exception as e:
            print(f"向量检索失败: {e}")
            return []
        finally:
            vector_search_duration.observe(time.time() - start_time)
    
    def _reciprocal_rank_fusion(
        self,
        result_lists: List[List[BlockCandidate]],
        k: int = 60
    ) -> List[BlockCandidate]:
        """
        RRF (Reciprocal Rank Fusion) 算法
        
        公式: RRF(d) = Σ 1 / (k + rank(d))
        其中 k 是常数（通常为 60），rank(d) 是文档在列表中的排名
        """
        # 收集所有候选
        all_candidates = {}
        
        for result_list in result_lists:
            for rank, candidate in enumerate(result_list, start=1):
                block_id = candidate.block_id
                
                if block_id not in all_candidates:
                    all_candidates[block_id] = {
                        'candidate': candidate,
                        'rrf_score': 0.0
                    }
                
                # 累加 RRF 分数
                all_candidates[block_id]['rrf_score'] += 1.0 / (k + rank)
        
        # 按 RRF 分数排序
        sorted_candidates = sorted(
            all_candidates.values(),
            key=lambda x: x['rrf_score'],
            reverse=True
        )
        
        # 更新候选的分数为 RRF 分数
        result = []
        for item in sorted_candidates:
            candidate = item['candidate']
            candidate.score = item['rrf_score']
            result.append(candidate)
        
        return result
    
    def _meilisearch_search(
        self,
        query: str,
        doc_id: str,
        rev_id: str,
        scope_hint: Optional[ScopeHint],
        top_k: int
    ) -> List[BlockCandidate]:
        """使用 Meilisearch 搜索"""
        start_time = time.time()
        try:
            # 构建过滤器
            filters = {}
            if scope_hint:
                block_type = None
                if isinstance(scope_hint, dict):
                    block_type = scope_hint.get("block_type")
                else:
                    block_type = getattr(scope_hint, "block_type", None)
                
                if block_type:
                    filters['block_type'] = block_type
            
            # 搜索
            results = self.indexer.search(query, doc_id, rev_id, filters, top_k * 2)
            
            # 转换为 BlockCandidate
            candidates = []
            for result in results:
                # 计算分数（Meilisearch 不直接返回分数，使用排名）
                score = 1.0 / (results.index(result) + 1)
                
                # 如果有 heading 提示，增加权重
                if scope_hint:
                    heading = None
                    if isinstance(scope_hint, dict):
                        heading = scope_hint.get("heading")
                    else:
                        heading = getattr(scope_hint, "heading", None)
                    
                    if heading and heading.lower() in result.get('parent_heading_text', '').lower():
                        score += 0.3
                
                # 如果有关键词提示，检查是否包含
                if scope_hint:
                    keywords = []
                    if isinstance(scope_hint, dict):
                        keywords = scope_hint.get("keywords", [])
                    else:
                        keywords = getattr(scope_hint, "keywords", [])
                    
                    for keyword in keywords:
                        if normalize_text(keyword) in normalize_text(result.get('plain_text', '')):
                            score += 0.2
                
                candidates.append(BlockCandidate(
                    block_id=result['block_id'],
                    snippet=result.get('plain_text', '')[:200],
                    heading_context=result.get('parent_heading_text', '（无标题）'),
                    order_index=result.get('order_index', 0),
                    score=min(score, 1.0),
                    block_type=result.get('block_type', 'paragraph')
                ))
            
            # 按分数排序
            candidates.sort(key=lambda x: x.score, reverse=True)
            return candidates[:top_k]
        finally:
            meilisearch_query_duration.observe(time.time() - start_time)

    def _simple_search(
        self,
        query: str,
        doc_id: str,
        rev_id: str,
        scope_hint: Optional[ScopeHint],
        top_k: int
    ) -> List[BlockCandidate]:
        """简单的关键词匹配搜索（降级方案）"""
        doc_uuid = uuid.UUID(doc_id)
        rev_uuid = uuid.UUID(rev_id)
        
        # 获取所有块
        blocks_query = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == rev_uuid
        )
        
        # 应用 scope_hint 过滤
        if scope_hint:
            block_type = None
            if isinstance(scope_hint, dict):
                block_type = scope_hint.get("block_type")
            else:
                block_type = getattr(scope_hint, "block_type", None)
            
            if block_type:
                blocks_query = blocks_query.filter(
                    db_models.BlockVersion.block_type == block_type
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
            if scope_hint:
                heading = None
                if isinstance(scope_hint, dict):
                    heading = scope_hint.get("heading")
                else:
                    heading = getattr(scope_hint, "heading", None)
                
                if heading:
                    # 获取父级 heading
                    parent_heading = self._get_parent_heading(block)
                    if parent_heading and heading.lower() in parent_heading.lower():
                        score += 0.3
            
            # 如果有关键词提示，检查是否包含
            if scope_hint:
                keywords = []
                if isinstance(scope_hint, dict):
                    keywords = scope_hint.get("keywords", [])
                else:
                    keywords = getattr(scope_hint, "keywords", [])
                
                for keyword in keywords:
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
    
    def _get_parent_heading_by_id(self, block_id: str, rev_id: str) -> Optional[str]:
        """通过 block_id 获取父级标题"""
        block_uuid = uuid.UUID(block_id)
        rev_uuid = uuid.UUID(rev_id)
        
        block = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.block_id == block_uuid,
            db_models.BlockVersion.rev_id == rev_uuid
        ).first()
        
        if not block:
            return None
        
        return self._get_parent_heading(block)
    
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
