"""
检索工具 - 封装所有检索相关操作
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import uuid

from app.tools.base import BaseTool
from app.services.retriever import HybridRetriever
from app.models import database as db_models


# ============ Input Schemas ============

class SearchInput(BaseModel):
    query: str = Field(description="搜索查询")
    doc_id: str = Field(description="文档 ID (UUID)")
    rev_id: str = Field(description="版本 ID (UUID)")
    top_k: int = Field(default=10, description="返回结果数量")
    scope_hint: Optional[str] = Field(default=None, description="范围提示（如章节名称）")


# ============ Tools ============

class HybridSearchTool(BaseTool):
    name: str = "search_hybrid"
    description: str = """执行混合检索（BM25 + 向量 + RRF 融合）。
    这是最推荐的检索方式，结合了关键词匹配和语义理解的优势。
    适用于大多数场景。"""
    args_schema: type[BaseModel] = SearchInput
    
    def _run(
        self,
        query: str,
        doc_id: str,
        rev_id: str,
        top_k: int = 10,
        scope_hint: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """执行混合检索"""
        retriever = HybridRetriever(self.db)
        
        try:
            candidates = retriever.search(
                query=query,
                doc_id=doc_id,
                rev_id=rev_id,
                scope_hint=scope_hint,
                top_k=top_k
            )
            
            return [
                {
                    "block_id": c.block_id,
                    "snippet": c.snippet,
                    "heading_context": c.heading_context,
                    "order_index": c.order_index,
                    "score": c.score,
                    "match_type": "hybrid"
                }
                for c in candidates
            ]
        except Exception as e:
            return [{"error": str(e)}]


class BM25SearchTool(BaseTool):
    name: str = "search_bm25"
    description: str = """执行 BM25 关键词检索。
    适用于用户明确提到关键词的场景，如"找到包含'付款条款'的段落"。
    优点：精确匹配，速度快。
    缺点：无法理解语义。"""
    args_schema: type[BaseModel] = SearchInput
    
    def _run(
        self,
        query: str,
        doc_id: str,
        rev_id: str,
        top_k: int = 10,
        scope_hint: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """执行 BM25 检索"""
        retriever = HybridRetriever(self.db)
        
        try:
            # 使用 retriever 的 BM25 部分
            candidates = retriever._bm25_search(
                query=query,
                doc_id=doc_id,
                rev_id=rev_id,
                top_k=top_k
            )
            
            return [
                {
                    "block_id": c.block_id,
                    "snippet": c.snippet,
                    "heading_context": c.heading_context,
                    "order_index": c.order_index,
                    "score": c.score,
                    "match_type": "bm25"
                }
                for c in candidates
            ]
        except Exception as e:
            return [{"error": str(e)}]


class VectorSearchTool(BaseTool):
    name: str = "search_vector"
    description: str = """执行向量语义检索。
    适用于用户使用自然语言描述的场景，如"找到关于钱的那段"。
    优点：理解语义，可以找到意思相近但用词不同的内容。
    缺点：可能不够精确。"""
    args_schema: type[BaseModel] = SearchInput
    
    def _run(
        self,
        query: str,
        doc_id: str,
        rev_id: str,
        top_k: int = 10,
        scope_hint: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """执行向量检索"""
        retriever = HybridRetriever(self.db)
        
        try:
            # 使用 retriever 的向量检索部分
            candidates = retriever._vector_search(
                query=query,
                doc_id=doc_id,
                rev_id=rev_id,
                top_k=top_k
            )
            
            return [
                {
                    "block_id": c.block_id,
                    "snippet": c.snippet,
                    "heading_context": c.heading_context,
                    "order_index": c.order_index,
                    "score": c.score,
                    "match_type": "vector"
                }
                for c in candidates
            ]
        except Exception as e:
            return [{"error": str(e)}]
