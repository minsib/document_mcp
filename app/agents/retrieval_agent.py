"""
Retrieval Agent - 检索定位智能体
负责查找和定位目标块，提供完整的位置信息
"""
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from app.tools.search_tools import HybridSearchTool, BM25SearchTool, VectorSearchTool
from app.tools.db_tools import GetBlocksTool, GetBlockContextTool
from app.tools.llm_tools import VerifyTargetTool
from app.tools.index_tools import GetIndexInfoTool
from app.utils.intent_helper import get_intent_attr


def create_retrieval_agent(db: Session):
    """创建检索智能体"""
    return RetrievalAgent(db)


class RetrievalAgent:
    """检索定位智能体"""
    
    def __init__(self, db: Session):
        self.db = db
        
        # 初始化工具
        self.hybrid_search = HybridSearchTool(db=db)
        self.bm25_search = BM25SearchTool(db=db)
        self.vector_search = VectorSearchTool(db=db)
        self.get_blocks = GetBlocksTool(db=db)
        self.get_context = GetBlockContextTool(db=db)
        self.verify_target = VerifyTargetTool(db=db)
        self.get_index_info = GetIndexInfoTool(db=db)
    
    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行检索定位"""
        intent = state.get("intent")
        doc_id = state["doc_id"]
        rev_id = state["active_rev_id"]
        user_message = state["user_message"]
        
        # 1. 选择检索策略并执行
        candidates = self._execute_search(
            query=user_message,
            doc_id=doc_id,
            rev_id=rev_id,
            intent=intent
        )
        
        if not candidates:
            state["errors"] = state.get("errors", []) + [{
                "type": "no_candidates",
                "message": "未找到匹配的内容"
            }]
            state["next_action"] = "end"
            return state
        
        # 2. LLM 验证候选结果
        verified_candidates = self._verify_candidates(
            candidates=candidates,
            intent=intent
        )
        
        if not verified_candidates:
            state["errors"] = state.get("errors", []) + [{
                "type": "verification_failed",
                "message": "候选结果验证失败"
            }]
            state["next_action"] = "end"
            return state
        
        # 3. 收集完整位置信息
        target_locations = []
        for candidate in verified_candidates[:3]:  # 最多返回 3 个候选
            location = self._collect_location_info(
                block_id=candidate["block_id"],
                doc_id=doc_id,
                rev_id=rev_id,
                candidate=candidate
            )
            target_locations.append(location)
        
        # 4. 判断是否需要消歧
        if len(target_locations) > 1:
            state["target_locations"] = target_locations
            state["needs_disambiguation"] = True
            state["next_action"] = "end"
            return state
        
        # 5. 单个目标，直接进入编辑
        state["selected_target"] = target_locations[0]
        state["target_locations"] = target_locations
        state["next_action"] = "edit"
        
        return state
    
    def _execute_search(
        self,
        query: str,
        doc_id: str,
        rev_id: str,
        intent: Any
    ) -> List[Dict[str, Any]]:
        """执行检索"""
        # 默认使用混合检索
        scope_hint = get_intent_attr(intent, "scope_hint", None) if intent else None
        
        results = self.hybrid_search._run(
            query=query,
            doc_id=doc_id,
            rev_id=rev_id,
            top_k=10,
            scope_hint=scope_hint
        )
        
        return [r for r in results if "error" not in r]
    
    def _verify_candidates(
        self,
        candidates: List[Dict[str, Any]],
        intent: Any
    ) -> List[Dict[str, Any]]:
        """验证候选结果"""
        verified = []
        
        for candidate in candidates:
            # 使用 LLM 验证
            user_message = get_intent_attr(intent, "user_message", "") if intent else ""
            operation = get_intent_attr(intent, "operation", "replace") if intent else "replace"
            
            result = self.verify_target._run(
                intent_description=user_message,
                candidate_content=candidate.get("snippet", ""),
                operation=operation
            )
            
            if result.get("is_match") and result.get("confidence", 0) > 0.7:
                candidate["verification"] = result
                verified.append(candidate)
        
        return verified
    
    def _collect_location_info(
        self,
        block_id: str,
        doc_id: str,
        rev_id: str,
        candidate: Dict[str, Any]
    ) -> Dict[str, Any]:
        """收集完整位置信息"""
        # 获取块详细信息
        blocks = self.get_blocks._run(rev_id=rev_id, block_ids=[block_id])
        block = blocks[0] if blocks else {}
        
        # 获取上下文
        context = self.get_context._run(
            block_id=block_id,
            rev_id=rev_id,
            window=2
        )
        
        # 获取索引信息
        index_info = self.get_index_info._run(
            block_id=block_id,
            doc_id=doc_id
        )
        
        return {
            "block_id": block_id,
            "block_version_id": block.get("block_version_id"),
            "rev_id": rev_id,
            "content": block.get("content_md", ""),
            "plain_text": block.get("plain_text", ""),
            "block_type": block.get("block_type", ""),
            "order_index": block.get("order_index", 0),
            "heading_context": block.get("heading_context", ""),
            "db_location": {
                "table": "block_versions",
                "primary_key": block.get("block_version_id"),
                "schema": "public"
            },
            "meilisearch_index": {
                "index_name": "blocks",
                "document_id": index_info.get("document_id"),
                "indexed_at": index_info.get("indexed_at"),
                "exists": index_info.get("exists", False)
            },
            "context": context,
            "confidence": candidate.get("verification", {}).get("confidence", 0.8),
            "match_reason": candidate.get("verification", {}).get("reason", ""),
            "retrieval_scores": {
                "search_score": candidate.get("score", 0),
                "match_type": candidate.get("match_type", "hybrid")
            }
        }
