from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.schemas import PreviewDiff, DiffItem
from app.models import database as db_models
from app.nodes.intent_clarifier import SemanticConflictDetector
from app.utils.markdown import strip_markdown
import uuid
import hashlib
import json
import time


class PreviewGeneratorNode:
    """预览生成节点"""
    
    def __init__(self, db: Session, cache_manager=None):
        self.db = db
        self.conflict_detector = SemanticConflictDetector(db)
        if cache_manager:
            self.cache = cache_manager
        else:
            try:
                from app.services.cache import get_cache_manager
                self.cache = get_cache_manager()
            except:
                self.cache = None
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """生成预览"""
        edit_plan_dict = state.get("edit_plan")
        if not edit_plan_dict:
            state["errors"] = state.get("errors", []) + [{"type": "no_edit_plan", "message": "没有编辑计划"}]
            return state
        
        # 获取目标块
        blocks = {}
        operations = edit_plan_dict.get("operations", [])
        for op in operations:
            target_block_id = op.get("target_block_id") if isinstance(op, dict) else op.target_block_id
            block = self._get_block(target_block_id, state["active_rev_id"])
            if block:
                blocks[target_block_id] = block
        
        # 生成 diff
        diffs = []
        total_chars_added = 0
        total_chars_removed = 0
        grouped = {}
        
        for op in operations:
            target_block_id = op.get("target_block_id") if isinstance(op, dict) else op.target_block_id
            op_type = op.get("op_type") if isinstance(op, dict) else op.op_type
            new_content_md = op.get("new_content_md") if isinstance(op, dict) else op.new_content_md
            
            block = blocks.get(target_block_id)
            if not block:
                continue
            
            before_snippet = block.plain_text[:200]
            
            if op_type == "replace":
                after_snippet = strip_markdown(new_content_md)[:200] if new_content_md else ""
                char_diff = len(new_content_md or "") - len(block.content_md)
            elif op_type == "delete":
                after_snippet = "[已删除]"
                char_diff = -len(block.content_md)
            elif op_type in ["insert_after", "insert_before"]:
                after_snippet = f"{before_snippet}\n\n[新增] {strip_markdown(new_content_md or '')[:100]}"
                char_diff = len(new_content_md or "")
            else:
                after_snippet = before_snippet
                char_diff = 0
            
            if char_diff > 0:
                total_chars_added += char_diff
            else:
                total_chars_removed += abs(char_diff)
            
            heading_context = self._get_parent_heading(block) or "（无标题）"
            
            # 语义冲突检测（仅对 replace 操作）
            if op_type == "replace" and new_content_md:
                context = self.conflict_detector.get_context(
                    target_block_id,
                    state["active_rev_id"],
                    window=1
                )
                conflict = self.conflict_detector.check_conflict(
                    block.plain_text,
                    strip_markdown(new_content_md),
                    context
                )
                if conflict and conflict.get("severity") == "high":
                    # 记录冲突警告
                    state.setdefault("warnings", []).append({
                        "type": "semantic_conflict",
                        "block_id": target_block_id,
                        "message": conflict["message"],
                        "suggestion": conflict.get("suggestion", "")
                    })
            
            diffs.append(DiffItem(
                block_id=target_block_id,
                op_type=op_type,
                before_snippet=before_snippet,
                after_snippet=after_snippet,
                heading_context=heading_context,
                char_diff=char_diff
            ))
            
            # 按章节分组
            grouped[heading_context] = grouped.get(heading_context, 0) + 1
        
        preview = PreviewDiff(
            diffs=diffs,
            total_changes=len(diffs),
            estimated_impact=edit_plan_dict.get("estimated_impact", "low"),
            grouped_by_heading=grouped,
            total_chars_added=total_chars_added,
            total_chars_removed=total_chars_removed
        )
        
        # 计算 preview_hash
        preview_json = json.dumps(preview.model_dump(), sort_keys=True)
        preview_hash = hashlib.sha256(preview_json.encode()).hexdigest()
        
        # 如果需要确认，生成 confirm_token
        requires_confirmation = edit_plan_dict.get("requires_confirmation", False)
        estimated_impact = edit_plan_dict.get("estimated_impact", "low")
        
        if requires_confirmation or estimated_impact == "high":
            token = self._generate_confirm_token(state, edit_plan_dict, preview, preview_hash)
            state["confirm_token"] = token
            state["preview_hash"] = preview_hash
            state["need_user_action"] = "confirm_preview"
        
        state["preview_diff"] = preview.model_dump()  # 转换为字典
        return state
    
    def _generate_confirm_token(self, state, edit_plan_dict, preview, preview_hash: str) -> str:
        """生成确认 token"""
        from uuid import uuid4
        
        token_id = str(uuid4())
        
        # 计算 plan_hash
        plan_json = json.dumps(edit_plan_dict, sort_keys=True)
        plan_hash = hashlib.sha256(plan_json.encode()).hexdigest()
        
        payload = {
            "token_id": token_id,
            "session_id": state["session_id"],
            "doc_id": state["doc_id"],
            "active_rev_id": state["active_rev_id"],
            "active_version": state["active_version"],
            "preview_hash": preview_hash,
            "plan_hash": plan_hash,
            "edit_plan": edit_plan_dict,
            "created_at": time.time(),
            "expires_at": time.time() + 900  # 15 分钟
        }
        
        # 存储到 Redis
        if self.cache:
            success = self.cache.store_confirm_token(
                state["session_id"],
                token_id,
                payload,
                900
            )
            if not success:
                # 降级：存储到状态中
                state["_confirm_payload"] = payload
        else:
            # 降级：存储到状态中（仅用于测试）
            state["_confirm_payload"] = payload
        
        return token_id
    
    def _get_block(self, block_id: str, rev_id: str) -> db_models.BlockVersion:
        """获取块"""
        return self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.block_id == uuid.UUID(block_id),
            db_models.BlockVersion.rev_id == uuid.UUID(rev_id)
        ).first()
    
    def _get_parent_heading(self, block: db_models.BlockVersion) -> str:
        """获取父级标题"""
        if not block.parent_heading_block_id:
            return None
        
        parent = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.block_id == block.parent_heading_block_id,
            db_models.BlockVersion.rev_id == block.rev_id
        ).first()
        
        return parent.plain_text if parent else None
