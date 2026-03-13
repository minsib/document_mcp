"""
索引工具 - 封装 Meilisearch 索引操作
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
import uuid
from datetime import datetime

from app.tools.base import BaseTool


# ============ Input Schemas ============

class IndexBlockInput(BaseModel):
    block_id: str = Field(description="块 ID (UUID)")
    doc_id: str = Field(description="文档 ID (UUID)")
    content: str = Field(description="块内容")
    metadata: Dict[str, Any] = Field(description="元数据（标题、类型等）")


class UpdateIndexInput(BaseModel):
    block_id: str = Field(description="块 ID (UUID)")
    doc_id: str = Field(description="文档 ID (UUID)")
    content: str = Field(description="新内容")


class SearchIndexInput(BaseModel):
    query: str = Field(description="搜索查询")
    doc_id: str = Field(description="文档 ID (UUID)")
    top_k: int = Field(default=10, description="返回结果数量")


class GetIndexInfoInput(BaseModel):
    block_id: str = Field(description="块 ID (UUID)")
    doc_id: str = Field(description="文档 ID (UUID)")


# ============ Tools ============

class IndexBlockTool(BaseTool):
    name: str = "index_block"
    description: str = """将块添加到 Meilisearch 索引。
    用于新创建的块或需要重新索引的块。"""
    args_schema: type[BaseModel] = IndexBlockInput
    
    def _run(
        self,
        block_id: str,
        doc_id: str,
        content: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """索引块"""
        try:
            from app.services.search_indexer import get_search_indexer
            
            indexer = get_search_indexer()
            document_id = f"{doc_id}_{block_id}"
            
            # 准备索引文档
            index_doc = {
                "id": document_id,
                "doc_id": doc_id,
                "block_id": block_id,
                "content": content,
                "indexed_at": datetime.utcnow().isoformat(),
                **metadata
            }
            
            # 添加到索引
            indexer.index_documents([index_doc])
            
            return {
                "success": True,
                "document_id": document_id,
                "indexed_at": index_doc["indexed_at"]
            }
        except Exception as e:
            return {"error": str(e), "success": False}


class UpdateIndexTool(BaseTool):
    name: str = "update_index"
    description: str = """更新 Meilisearch 索引中的块。
    用于块内容被修改后更新索引。"""
    args_schema: type[BaseModel] = UpdateIndexInput
    
    def _run(
        self,
        block_id: str,
        doc_id: str,
        content: str
    ) -> Dict[str, Any]:
        """更新索引"""
        try:
            from app.services.search_indexer import get_search_indexer
            
            indexer = get_search_indexer()
            document_id = f"{doc_id}_{block_id}"
            
            # 更新文档
            update_doc = {
                "id": document_id,
                "content": content,
                "indexed_at": datetime.utcnow().isoformat()
            }
            
            indexer.update_documents([update_doc])
            
            return {
                "success": True,
                "document_id": document_id,
                "updated_at": update_doc["indexed_at"]
            }
        except Exception as e:
            return {"error": str(e), "success": False}


class SearchIndexTool(BaseTool):
    name: str = "search_index"
    description: str = """在 Meilisearch 索引中搜索。
    执行全文检索，返回匹配的块。"""
    args_schema: type[BaseModel] = SearchIndexInput
    
    def _run(
        self,
        query: str,
        doc_id: str,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """搜索索引"""
        try:
            from app.services.search_indexer import get_search_indexer
            
            indexer = get_search_indexer()
            
            # 搜索
            results = indexer.search(
                query=query,
                filter=f"doc_id = {doc_id}",
                limit=top_k
            )
            
            return [
                {
                    "block_id": hit.get("block_id"),
                    "content": hit.get("content"),
                    "score": hit.get("_rankingScore", 0),
                    "document_id": hit.get("id")
                }
                for hit in results.get("hits", [])
            ]
        except Exception as e:
            return [{"error": str(e)}]


class GetIndexInfoTool(BaseTool):
    name: str = "get_index_info"
    description: str = """获取块在 Meilisearch 索引中的信息。
    返回索引状态、索引时间等元数据。"""
    args_schema: type[BaseModel] = GetIndexInfoInput
    
    def _run(
        self,
        block_id: str,
        doc_id: str
    ) -> Dict[str, Any]:
        """获取索引信息"""
        try:
            from app.services.search_indexer import get_search_indexer
            
            indexer = get_search_indexer()
            document_id = f"{doc_id}_{block_id}"
            
            # 获取文档
            doc = indexer.get_document(document_id)
            
            if doc:
                return {
                    "index_name": "blocks",
                    "document_id": document_id,
                    "indexed_at": doc.get("indexed_at"),
                    "exists": True
                }
            else:
                return {
                    "exists": False,
                    "document_id": document_id
                }
        except Exception as e:
            return {"error": str(e), "exists": False}
