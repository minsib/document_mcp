from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.schemas import EditPlan, EditOperation, EvidenceQuote
from app.models import database as db_models
from app.services.llm_client import get_qwen_client
from app.nodes.intent_clarifier import CrossReferenceResolver, SemanticConflictDetector
import json
import uuid


class EditPlannerNode:
    """编辑计划生成节点"""
    
    def __init__(self, db: Session):
        self.db = db
        self.llm = get_qwen_client()
        self.reference_resolver = CrossReferenceResolver(db)
        self.conflict_detector = SemanticConflictDetector(db)
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """生成编辑计划"""
        # 兼容新的工作流状态结构
        selected_target = state.get("selected_target")
        if not selected_target:
            state["errors"] = state.get("errors", []) + [{"type": "no_target", "message": "未选择目标块"}]
            return state
        
        intent_dict = state["intent"]
        operations = []
        
        # 将 selected_target 转换为 target 列表
        targets = [selected_target] if isinstance(selected_target, dict) else []
        
        for target in targets:
            # 从 target 字典中提取 block_id
            block_id = target.get("block_id") if isinstance(target, dict) else target.block_id
            
            # 获取目标块完整内容
            block = self._get_block(block_id, state["active_rev_id"])
            if not block:
                continue
            
            try:
                # 使用 LLM 生成编辑操作
                operation = self._generate_operation(intent_dict, target, block)
                operations.append(operation)
            except Exception as e:
                state["errors"] = state.get("errors", []) + [{"type": "plan_generation_failed", "message": str(e)}]
                return state
        
        edit_plan = EditPlan(
            doc_id=state["doc_id"],
            rev_id=state["active_rev_id"],
            operations=operations,
            estimated_impact=self._estimate_impact(operations),
            requires_confirmation=self._needs_confirmation(operations)
        )
        
        state["edit_plan"] = edit_plan.model_dump()  # 转换为字典
        return state
    
    def _generate_operation(self, intent_dict, target, block: db_models.BlockVersion) -> EditOperation:
        """生成单个编辑操作"""
        # 从 target 字典中提取信息
        if isinstance(target, dict):
            plain_text = target.get("plain_text", "")
            # 创建一个简单的 evidence
            evidence = EvidenceQuote(
                text=plain_text[:100],
                start=0,
                end=min(100, len(plain_text))
            )
        else:
            evidence = target.evidence
        
        operation = intent_dict.get("operation") if isinstance(intent_dict, dict) else intent_dict.operation
        
        if operation == "delete":
            return EditOperation(
                op_type="delete",
                target_block_id=str(block.block_id),
                evidence=evidence,
                new_content_md=None,
                rationale="用户要求删除此段落"
            )
        
        # 检查是否有跨段落引用
        referenced_content = None
        user_message = intent_dict.get('user_message', '') if isinstance(intent_dict, dict) else getattr(intent_dict, 'user_message', '')
        if user_message:
            reference = self.reference_resolver.resolve_reference(
                user_message,
                str(block.doc_id) if hasattr(block, 'doc_id') else '',
                str(block.rev_id)
            )
            if reference:
                referenced_content = reference
        
        # 对于 replace 和 insert 操作，使用 LLM 生成新内容
        system_prompt = """你是一个文档编辑助手。

关键规则：
1. 只修改目标块，不得引入无关段落
2. 严格遵守 constraints（tone, keep_length, must_include）
3. rationale 简短说明修改理由（< 200 字）
4. evidence_quote 原样透传
5. 对于 replace 操作，new_content_md 必须保持原有的 Markdown 格式
6. 保持段落的语义完整性
7. 如果提供了参考内容，理解用户意图：
   - "改成XX"通常是参考格式/结构，而非完全替换
   - 保持目标块的主题和核心内容
   - 只借鉴参考内容的表述方式、格式或结构

输出 JSON 格式：
{
  "new_content_md": "修改后的 Markdown 内容",
  "rationale": "修改理由",
  "reference_usage": "如何使用了参考内容（如果有）"
}
"""
        
        # 将 intent_dict 转换为 JSON 字符串
        import json
        intent_json = json.dumps(intent_dict, ensure_ascii=False, indent=2)
        
        user_content = f"""用户意图：
{intent_json}

目标块内容：
{block.content_md}

evidence_quote：{evidence.text}
"""
        
        # 如果有引用内容，添加到提示中
        if referenced_content:
            user_content += f"""

参考内容（第{referenced_content['number']}条）：
{referenced_content['content']}

注意：用户说"改成第{referenced_content['number']}条"，通常是指：
1. 参考其格式和结构（如编号方式、条款组织）
2. 参考其表述风格（如用词、语气）
3. 而不是完全替换内容

请保持目标块的主题，只借鉴参考内容的形式。
"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content + "\n请生成修改后的内容。输出 JSON："}
        ]
        
        response = self.llm.chat_completion_json(messages, temperature=0.7)
        result = json.loads(response)
        
        # 提取操作类型
        op_type = operation if operation != "multi_replace" else "replace"
        
        return EditOperation(
            op_type=op_type,
            target_block_id=str(block.block_id),
            evidence=evidence,
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
