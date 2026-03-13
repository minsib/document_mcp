"""
Edit Agent - 编辑执行智能体
负责基于定位信息执行完整的编辑流程
"""
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
import uuid

from app.tools.llm_tools import GenerateContentTool, CheckSemanticConflictTool
from app.tools.db_tools import CreateRevisionTool, UpdateBlockTool
from app.tools.index_tools import UpdateIndexTool
from app.models.schemas import EditPlan, EditOperation, PreviewDiff, DiffItem
from app.utils.intent_helper import get_intent_attr


def create_edit_agent(db: Session):
    """创建编辑执行智能体"""
    return EditAgent(db)


class EditAgent:
    """编辑执行智能体
    
    职责：
    1. 基于 TargetLocation 生成编辑计划
    2. 生成新内容
    3. 检测语义冲突
    4. 生成预览 diff
    5. 执行数据库操作
    6. 更新索引
    7. 清除缓存
    """
    
    def __init__(self, db: Session):
        self.db = db
        
        # 初始化工具
        self.generate_content_tool = GenerateContentTool(db=db)
        self.check_conflict_tool = CheckSemanticConflictTool(db=db)
        self.create_revision_tool = CreateRevisionTool(db=db)
        self.update_block_tool = UpdateBlockTool(db=db)
        self.update_index_tool = UpdateIndexTool(db=db)
    
    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行编辑流程
        
        Args:
            state: 工作流状态
            
        Returns:
            更新后的状态，包含编辑结果
        """
        selected_target = state.get("selected_target")
        intent = state.get("intent")
        
        # 1. 验证输入
        if not selected_target:
            state["errors"] = state.get("errors", []) + [{
                "type": "no_target",
                "message": "未选择目标块"
            }]
            state["next_action"] = "end"
            return state
        
        if not intent:
            state["errors"] = state.get("errors", []) + [{
                "type": "no_intent",
                "message": "缺少意图信息"
            }]
            state["next_action"] = "end"
            return state
        
        try:
            # 2. 生成编辑计划
            edit_plan = self._generate_edit_plan(selected_target, intent, state)
            
            if not edit_plan:
                state["errors"] = state.get("errors", []) + [{
                    "type": "plan_generation_failed",
                    "message": "编辑计划生成失败"
                }]
                state["next_action"] = "end"
                return state
            
            state["edit_plan"] = edit_plan
            
            # 3. 生成预览
            preview_result = self._generate_preview(edit_plan, selected_target, state)
            
            if not preview_result:
                state["errors"] = state.get("errors", []) + [{
                    "type": "preview_generation_failed",
                    "message": "预览生成失败"
                }]
                state["next_action"] = "end"
                return state
            
            state["preview_diff"] = preview_result["preview"]
            state["warnings"] = preview_result.get("warnings", [])
            
            # 4. 判断是否需要用户确认
            if self._needs_confirmation(edit_plan, preview_result):
                state["next_action"] = "end"
                state["needs_user_confirmation"] = True
                return state
            
            # 5. 执行修改
            apply_result = self._apply_edits(edit_plan, state)
            
            if not apply_result:
                state["errors"] = state.get("errors", []) + [{
                    "type": "apply_failed",
                    "message": "修改执行失败"
                }]
                state["next_action"] = "end"
                return state
            
            state["apply_result"] = apply_result
            state["new_rev_id"] = apply_result.get("new_rev_id")
            state["next_action"] = "end"
            
            # 6. 添加调试信息
            if state.get("debug_mode"):
                state["debug_info"] = state.get("debug_info", {})
                state["debug_info"]["edit_agent"] = {
                    "plan_operations": len(edit_plan.get("operations", [])),
                    "preview_changes": len(preview_result["preview"].get("diffs", [])),
                    "warnings_count": len(preview_result.get("warnings", [])),
                    "applied": bool(apply_result)
                }
            
            return state
            
        except Exception as e:
            state["errors"] = state.get("errors", []) + [{
                "type": "edit_agent_error",
                "message": f"编辑智能体执行失败: {str(e)}"
            }]
            state["next_action"] = "end"
            return state
    
    def _generate_edit_plan(
        self,
        target: Dict[str, Any],
        intent: Any,
        state: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """生成编辑计划
        
        Args:
            target: 目标位置信息
            intent: 用户意图
            state: 工作流状态
            
        Returns:
            编辑计划
        """
        try:
            operation = get_intent_attr(intent, "operation", "replace")
            user_message = get_intent_attr(intent, "user_message", "")
            block_id = target.get("block_id")
            
            # 1. 生成新内容（如果需要）
            new_content = None
            if operation != "delete":
                # 根据约束条件和用户消息生成新内容
                # 使用 LLM 生成新内容
                content_result = self.generate_content_tool._run(
                    instruction=user_message,
                    original_content=target.get("content", ""),
                    context=self._format_context(target.get("context"))
                )
                
                if "error" in content_result:
                    print(f"内容生成失败: {content_result['error']}")
                    return None
                
                new_content = content_result.get("content")
            
            # 2. 创建编辑操作
            operations = []
            
            if operation == "replace":
                operations.append({
                    "type": "replace",
                    "block_id": block_id,
                    "new_content": new_content,
                    "reason": user_message
                })
            
            elif operation == "delete":
                operations.append({
                    "type": "delete",
                    "block_id": block_id,
                    "reason": user_message
                })
            
            elif operation == "insert_after":
                operations.append({
                    "type": "insert_after",
                    "block_id": block_id,
                    "new_content": new_content,
                    "reason": user_message
                })
            
            elif operation == "insert_before":
                operations.append({
                    "type": "insert_before",
                    "block_id": block_id,
                    "new_content": new_content,
                    "reason": user_message
                })
            
            # 3. 创建编辑计划
            plan = {
                "operations": operations,
                "target_block_id": block_id,
                "operation_type": operation,
                "estimated_impact": self._estimate_impact(operations),
                "requires_confirmation": self._requires_confirmation(operation, operations)
            }
            
            return plan
            
        except Exception as e:
            print(f"编辑计划生成失败: {e}")
            return None
    
    def _generate_preview(
        self,
        edit_plan: Dict[str, Any],
        target: Dict[str, Any],
        state: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """生成预览
        
        Args:
            edit_plan: 编辑计划
            target: 目标位置信息
            state: 工作流状态
            
        Returns:
            预览结果（包含 preview 和 warnings）
        """
        try:
            diffs = []
            warnings = []
            
            for operation in edit_plan.get("operations", []):
                op_type = operation.get("type")
                block_id = operation.get("block_id")
                new_content = operation.get("new_content", "")
                
                # 获取原内容
                original_content = target.get("content", "")
                
                # 1. 检测语义冲突
                if op_type == "replace" and new_content:
                    conflict_result = self.check_conflict_tool._run(
                        original_content=original_content,
                        new_content=new_content,
                        context=self._format_context(target.get("context"))
                    )
                    
                    if conflict_result.get("has_conflict"):
                        warnings.append({
                            "type": "semantic_conflict",
                            "severity": conflict_result.get("severity", "medium"),
                            "message": conflict_result.get("description", "检测到语义冲突"),
                            "suggestion": conflict_result.get("suggestion", "")
                        })
                
                # 2. 创建 diff 项
                if op_type == "replace":
                    diffs.append({
                        "block_id": block_id,
                        "op_type": "replace",
                        "before_snippet": original_content[:200],
                        "after_snippet": new_content[:200] if new_content else "",
                        "heading_context": target.get("heading_context", ""),
                        "char_diff": len(new_content) - len(original_content) if new_content else 0
                    })
                
                elif op_type == "delete":
                    diffs.append({
                        "block_id": block_id,
                        "op_type": "delete",
                        "before_snippet": original_content[:200],
                        "after_snippet": "",
                        "heading_context": target.get("heading_context", ""),
                        "char_diff": -len(original_content)
                    })
                
                elif op_type in ["insert_after", "insert_before"]:
                    diffs.append({
                        "block_id": block_id,
                        "op_type": op_type,
                        "before_snippet": "",
                        "after_snippet": new_content[:200] if new_content else "",
                        "heading_context": target.get("heading_context", ""),
                        "char_diff": len(new_content) if new_content else 0
                    })
            
            # 3. 创建预览对象
            preview = {
                "diffs": diffs,
                "total_changes": len(diffs),
                "estimated_impact": edit_plan.get("estimated_impact", "low")
            }
            
            return {
                "preview": preview,
                "warnings": warnings
            }
            
        except Exception as e:
            print(f"预览生成失败: {e}")
            return None
    
    def _apply_edits(
        self,
        edit_plan: Dict[str, Any],
        state: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """执行编辑操作
        
        Args:
            edit_plan: 编辑计划
            state: 工作流状态
            
        Returns:
            执行结果
        """
        try:
            doc_id = state.get("doc_id")
            user_id = state.get("user_id")
            parent_rev_id = state.get("active_rev_id")
            
            # 1. 创建新版本
            rev_result = self.create_revision_tool._run(
                doc_id=doc_id,
                parent_rev_id=parent_rev_id,
                user_id=user_id,
                change_summary=self._generate_change_summary(edit_plan)
            )
            
            if "error" in rev_result:
                print(f"创建版本失败: {rev_result['error']}")
                return None
            
            new_rev_id = rev_result.get("rev_id")
            
            # 2. 执行每个操作
            updated_blocks = []
            
            for operation in edit_plan.get("operations", []):
                op_type = operation.get("type")
                block_id = operation.get("block_id")
                new_content = operation.get("new_content", "")
                
                if op_type == "replace":
                    # 更新块
                    from app.utils.markdown import strip_markdown
                    
                    update_result = self.update_block_tool._run(
                        block_id=block_id,
                        rev_id=new_rev_id,
                        content_md=new_content,
                        plain_text=strip_markdown(new_content)
                    )
                    
                    if "error" not in update_result:
                        updated_blocks.append(block_id)
                        
                        # 更新索引
                        self.update_index_tool._run(
                            block_id=block_id,
                            doc_id=doc_id,
                            content=new_content
                        )
                
                # TODO: 实现 delete, insert_after, insert_before 操作
            
            # 3. 更新活跃版本
            self._update_active_revision(doc_id, new_rev_id, rev_result.get("version"))
            
            # 4. 清除缓存
            self._clear_cache(doc_id)
            
            return {
                "new_rev_id": new_rev_id,
                "version": rev_result.get("version"),
                "updated_blocks": updated_blocks,
                "operations_count": len(edit_plan.get("operations", []))
            }
            
        except Exception as e:
            print(f"编辑执行失败: {e}")
            # 回滚事务
            self.db.rollback()
            return None
    
    def _format_context(self, context: Optional[Dict[str, Any]]) -> str:
        """格式化上下文信息
        
        Args:
            context: 上下文字典
            
        Returns:
            格式化的上下文字符串
        """
        if not context:
            return ""
        
        parts = []
        
        # 前文
        before = context.get("before", [])
        if before:
            parts.append("前文：")
            for block in before[-2:]:  # 最多 2 个
                parts.append(f"  {block.get('content', '')[:100]}")
        
        # 后文
        after = context.get("after", [])
        if after:
            parts.append("后文：")
            for block in after[:2]:  # 最多 2 个
                parts.append(f"  {block.get('content', '')[:100]}")
        
        return "\n".join(parts)
    
    def _estimate_impact(self, operations: List[Dict[str, Any]]) -> str:
        """估计影响范围
        
        Args:
            operations: 操作列表
            
        Returns:
            影响级别 (low/medium/high)
        """
        if len(operations) == 1:
            op_type = operations[0].get("type")
            if op_type == "delete":
                return "medium"
            return "low"
        elif len(operations) <= 3:
            return "medium"
        else:
            return "high"
    
    def _requires_confirmation(
        self,
        operation: str,
        operations: List[Dict[str, Any]]
    ) -> bool:
        """判断是否需要用户确认
        
        Args:
            operation: 操作类型
            operations: 操作列表
            
        Returns:
            是否需要确认
        """
        # 删除操作总是需要确认
        if operation == "delete":
            return True
        
        # 批量操作需要确认
        if operation == "multi_replace":
            return True
        
        # 多个操作需要确认
        if len(operations) > 1:
            return True
        
        return False
    
    def _needs_confirmation(
        self,
        edit_plan: Dict[str, Any],
        preview_result: Dict[str, Any]
    ) -> bool:
        """判断是否需要用户确认
        
        Args:
            edit_plan: 编辑计划
            preview_result: 预览结果
            
        Returns:
            是否需要确认
        """
        # 计划要求确认
        if edit_plan.get("requires_confirmation"):
            return True
        
        # 有警告需要确认
        if preview_result.get("warnings"):
            return True
        
        # 影响范围大需要确认
        if edit_plan.get("estimated_impact") in ["medium", "high"]:
            return True
        
        return False
    
    def _generate_change_summary(self, edit_plan: Dict[str, Any]) -> str:
        """生成修改摘要
        
        Args:
            edit_plan: 编辑计划
            
        Returns:
            修改摘要
        """
        operations = edit_plan.get("operations", [])
        op_type = edit_plan.get("operation_type", "unknown")
        
        type_names = {
            "replace": "替换",
            "delete": "删除",
            "insert_after": "插入",
            "insert_before": "插入",
            "multi_replace": "批量替换"
        }
        
        type_name = type_names.get(op_type, "修改")
        count = len(operations)
        
        if count == 1:
            return f"{type_name}内容"
        else:
            return f"{type_name} {count} 处内容"
    
    def _update_active_revision(self, doc_id: str, rev_id: str, version: int):
        """更新活跃版本
        
        Args:
            doc_id: 文档 ID
            rev_id: 版本 ID
            version: 版本号
        """
        from app.models import database as db_models
        
        doc_uuid = uuid.UUID(doc_id)
        rev_uuid = uuid.UUID(rev_id)
        
        # 更新或创建活跃版本记录
        active_rev = self.db.query(db_models.DocumentActiveRevision).filter(
            db_models.DocumentActiveRevision.doc_id == doc_uuid
        ).first()
        
        if active_rev:
            active_rev.rev_id = rev_uuid
            active_rev.version = version
        else:
            active_rev = db_models.DocumentActiveRevision(
                doc_id=doc_uuid,
                rev_id=rev_uuid,
                version=version
            )
            self.db.add(active_rev)
        
        self.db.commit()
    
    def _clear_cache(self, doc_id: str):
        """清除缓存
        
        Args:
            doc_id: 文档 ID
        """
        try:
            from app.services.cache import get_cache_manager
            
            cache = get_cache_manager()
            if cache:
                # 清除文档相关的所有缓存
                cache.delete_pattern(f"doc:{doc_id}:*")
        except Exception as e:
            print(f"清除缓存失败: {e}")
