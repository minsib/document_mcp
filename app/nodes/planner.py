from typing import Dict, Any
from sqlalchemy.orm import Session
from app.models.schemas import EditPlan, EditOperation
from app.models import database as db_models
from app.services.llm_client import get_qwen_client
import json
import uuid


class EditPlannerNode:
    """编辑计划生成节点"""
    
    def __init__(self, db: Session):
        self.db = db
        self.llm = get_qwen_client()
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """生成编辑计划"""
        selection = state.get("selection")
        if not selection or not selection.targets:
            state["error"] = {"code": "no_target", "message": "未选择目标块"}
            return state
        
        intent = state["intent"]
        operations = []
        
        for target in selection.targets:
            # 获取目标块完整内容
            block = self._get_block(target.block_id, state["active_rev_id"])
            if not block:
                continue
            
            try:
                # 使用 LLM 生成编辑操作
                operation = self._generate_operation(intent, target, block)
                operations.append(operation)
            except Exception as e:
                state["error"] = {"code": "plan_generation_failed", "message": str(e)}
                return state
        
        edit_plan = EditPlan(
            doc_id=state["doc_id"],
            rev_id=state["active_rev_id"],
            operations=operations,
            estimated_impact=self._estimate_impact(operations),
            requires_confirmation=self._needs_confirmation(operations)
        )
        
        state["edit_plan"] = edit_plan
        return state
    
    def _generate_operation(self, intent, target, block: db_models.BlockVersion) -> EditOperation:
        """生成单个编辑操作"""
        if intent.operation == "delete":
            return EditOperation(
                op_type="delete",
                target_block_id=str(block.block_id),
                evidence=target.evidence,
                new_content_md=None,
                rationale="用户要求删除此段落"
            )
        
        # 对于 replace 和 insert 操作，使用 LLM 生成新内容
        system_prompt = """你是一个文档编辑助手。

关键规则：
1. 只修改目标块，不得引入无关段落
2. 严格遵守 constraints（tone, keep_length, must_include）
3. rationale 简短说明修改理由（< 200 字）
4. evidence_quote 原样透传
5. 对于 replace 操作，new_content_md 必须保持原有的 Markdown 格式
6. 保持段落的语义完整性

输出 JSON 格式：
{
  "new_content_md": "修改后的 Markdown 内容",
  "rationale": "修改理由"
}
"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"""用户意图：
{intent.model_dump_json(indent=2)}

目标块内容：
{block.content_md}

evidence_quote：{target.evidence.text}

请生成修改后的内容。输出 JSON："""}
        ]
        
        response = self.llm.chat_completion_json(messages, temperature=0.7)
        result = json.loads(response)
        
        return EditOperation(
            op_type=intent.operation if intent.operation != "multi_replace" else "replace",
            target_block_id=str(block.block_id),
            evidence=target.evidence,
            new_content_md=result.get("new_content_md"),
            rationale=result.get("rationale", "")[:200]
        )
    
    def _estimate_impact(self, operations) -> str:
        """评估影响程度"""
        if any(op.op_type == "delete" for op in operations):
            return "high"
        if len(operations) > 3:
            return "medium"
        return "low"
    
    def _needs_confirmation(self, operations) -> bool:
        """判断是否需要确认"""
        return any(op.op_type in ["delete", "move"] for op in operations)
    
    def _get_block(self, block_id: str, rev_id: str) -> db_models.BlockVersion:
        """获取块"""
        return self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.block_id == uuid.UUID(block_id),
            db_models.BlockVersion.rev_id == uuid.UUID(rev_id)
        ).first()
