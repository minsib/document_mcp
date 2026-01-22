from typing import Dict, Any
from sqlalchemy.orm import Session
from app.models.schemas import PreviewDiff, DiffItem
from app.models import database as db_models
from app.utils.markdown import strip_markdown
import uuid
import hashlib
import json
import time


class PreviewGeneratorNode:
    """预览生成节点"""
    
    def __init__(self, db: Session, redis_client=None):
        self.db = db
        self.redis = redis_client
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """生成预览"""
        edit_plan = state.get("edit_plan")
        if not edit_plan:
            state["error"] = {"code": "no_edit_plan", "message": "没有编辑计划"}
            return state
        
        # 获取目标块
        blocks = {}
        for op in edit_plan.operations:
            block = self._get_block(op.target_block_id, state["active_rev_id"])
            if block:
                blocks[op.target_block_id] = block
        
        # 生成 diff
        diffs = []
        total_chars_added = 0
        total_chars_removed = 0
        grouped = {}
        
        for op in edit_plan.operations:
            block = blocks.get(op.target_block_id)
            if not block:
                continue
            
            before_snippet = block.plain_text[:200]
            
            if op.op_type == "replace":
                after_snippet = strip_markdown(op.new_content_md)[:200] if op.new_content_md else ""
                char_diff = len(op.new_content_md or "") - len(block.content_md)
            elif op.op_type == "delete":
                after_snippet = "[已删除]"
                char_diff = -len(block.content_md)
            elif op.op_type in ["insert_after", "insert_before"]:
                after_snippet = f"{before_snippet}\n\n[新增] {strip_markdown(op.new_content_md or '')[:100]}"
                char_diff = len(op.new_content_md or "")
            else:
                after_snippet = before_snippet
                char_diff = 0
            
            if char_diff > 0:
                total_chars_added += char_diff
            else:
                total_chars_removed += abs(char_diff)
            
            heading_context = self._get_parent_heading(block) or "（无标题）"
            
            diffs.append(DiffItem(
                block_id=op.target_block_id,
                op_type=op.op_type,
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
            estimated_impact=edit_plan.estimated_impact,
            grouped_by_heading=grouped,
            total_chars_added=total_chars_added,
            total_chars_removed=total_chars_removed
        )
        
        # 计算 preview_hash
        preview_json = json.dumps(preview.model_dump(), sort_keys=True)
        preview_hash = hashlib.sha256(preview_json.encode()).hexdigest()
        
        # 如果需要确认，生成 confirm_token
        if edit_plan.requires_confirmation or edit_plan.estimated_impact == "high":
            token = self._generate_confirm_token(state, edit_plan, preview, preview_hash)
            state["confirm_token"] = token
            state["preview_hash"] = preview_hash
            state["need_user_action"] = "confirm_preview"
        
        state["preview_diff"] = preview
        return state
    
    def _generate_confirm_token(self, state, edit_plan, preview, preview_hash: str) -> str:
        """生成确认 token"""
        from uuid import uuid4
        
        token_id = str(uuid4())
        
        # 计算 plan_hash
        plan_json = json.dumps(edit_plan.model_dump(), sort_keys=True)
        plan_hash = hashlib.sha256(plan_json.encode()).hexdigest()
        
        payload = {
            "token_id": token_id,
            "session_id": state["session_id"],
            "doc_id": state["doc_id"],
            "active_rev_id": state["active_rev_id"],
            "active_version": state["active_version"],
            "preview_hash": preview_hash,
            "plan_hash": plan_hash,
            "edit_plan": edit_plan.model_dump(),
            "created_at": time.time(),
            "expires_at": time.time() + 900  # 15 分钟
        }
        
        # 存储到 Redis（如果可用）
        if self.redis:
            self.redis.setex(
                f"confirm_token:{state['session_id']}:{token_id}",
                900,
                json.dumps(payload)
            )
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
