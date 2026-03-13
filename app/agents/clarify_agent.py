"""
Clarify Agent - 澄清确认智能体
负责处理模糊意图，生成澄清问题
"""
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from app.nodes.intent_clarifier import CrossReferenceResolver
from app.utils.intent_helper import get_intent_attr


def create_clarify_agent(db: Session):
    """创建澄清确认智能体"""
    return ClarifyAgent(db)


class ClarifyAgent:
    """澄清确认智能体
    
    职责：
    1. 生成澄清问题和选项
    2. 解析跨段落引用
    3. 提供上下文帮助用户理解
    4. 处理用户的澄清响应
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.reference_resolver = CrossReferenceResolver(db)
    
    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行澄清处理
        
        Args:
            state: 工作流状态
            
        Returns:
            更新后的状态，包含澄清信息
        """
        clarification = state.get("clarification")
        user_message = state.get("user_message", "")
        
        # 1. 验证澄清信息存在
        if not clarification:
            state["errors"] = state.get("errors", []) + [{
                "type": "no_clarification",
                "message": "缺少澄清信息"
            }]
            state["next_action"] = "end"
            return state
        
        try:
            # 2. 根据澄清类型处理
            clarification_type = clarification.get("type")
            
            if clarification_type == "cross_reference":
                # 处理跨段落引用
                enhanced_clarification = self._handle_cross_reference(
                    clarification,
                    user_message,
                    state.get("doc_id"),
                    state.get("active_rev_id")
                )
                state["clarification"] = enhanced_clarification
            
            elif clarification_type == "ambiguous":
                # 处理模糊表达
                enhanced_clarification = self._handle_ambiguity(
                    clarification,
                    user_message
                )
                state["clarification"] = enhanced_clarification
            
            elif clarification_type == "large_scope":
                # 处理大范围修改
                enhanced_clarification = self._handle_large_scope(
                    clarification,
                    state.get("intent")
                )
                state["clarification"] = enhanced_clarification
            
            elif clarification_type == "delete_operation":
                # 处理删除操作
                enhanced_clarification = self._handle_delete_operation(
                    clarification
                )
                state["clarification"] = enhanced_clarification
            
            # 3. 标记需要用户响应
            state["next_action"] = "end"
            
            # 4. 添加调试信息
            if state.get("debug_mode"):
                state["debug_info"] = state.get("debug_info", {})
                state["debug_info"]["clarify_agent"] = {
                    "clarification_type": clarification_type,
                    "options_count": len(clarification.get("options", []))
                }
            
            return state
            
        except Exception as e:
            state["errors"] = state.get("errors", []) + [{
                "type": "clarify_agent_error",
                "message": f"澄清智能体执行失败: {str(e)}"
            }]
            state["next_action"] = "end"
            return state
    
    def _handle_cross_reference(
        self,
        clarification: Dict[str, Any],
        user_message: str,
        doc_id: str,
        rev_id: str
    ) -> Dict[str, Any]:
        """处理跨段落引用
        
        Args:
            clarification: 原始澄清信息
            user_message: 用户消息
            doc_id: 文档 ID
            rev_id: 版本 ID
            
        Returns:
            增强的澄清信息
        """
        # 尝试解析引用
        reference = self.reference_resolver.resolve_reference(
            user_message=user_message,
            doc_id=doc_id,
            rev_id=rev_id
        )
        
        if reference:
            # 找到了引用的内容，提供更详细的选项
            clarification["reference_content"] = {
                "number": reference.get("number"),
                "content": reference.get("plain_text", "")[:200],  # 限制长度
                "block_id": reference.get("block_id")
            }
            
            # 更新问题
            clarification["question"] = f"""检测到您引用了第 {reference.get('number')} 条的内容：

"{reference.get('plain_text', '')[:100]}..."

您是想：
1. 完全替换为这段内容？
2. 参考这段内容的格式来改写？
3. 参考这段内容的表述方式？"""
        
        return clarification
    
    def _handle_ambiguity(
        self,
        clarification: Dict[str, Any],
        user_message: str
    ) -> Dict[str, Any]:
        """处理模糊表达
        
        Args:
            clarification: 原始澄清信息
            user_message: 用户消息
            
        Returns:
            增强的澄清信息
        """
        # 添加示例帮助用户理解
        clarification["examples"] = [
            "明确的例子：把第三段的'项目背景'改成'项目简介'",
            "明确的例子：在第二章后面添加一段关于技术选型的说明",
            "明确的例子：删除关于付款条款的那一段"
        ]
        
        return clarification
    
    def _handle_large_scope(
        self,
        clarification: Dict[str, Any],
        intent: Any
    ) -> Dict[str, Any]:
        """处理大范围修改
        
        Args:
            clarification: 原始澄清信息
            intent: 用户意图
            
        Returns:
            增强的澄清信息
        """
        # 添加影响范围说明
        operation = get_intent_attr(intent, "operation", None) if intent else None
        
        if operation == "multi_replace":
            clarification["impact"] = {
                "type": "批量替换",
                "description": "此操作将修改文档中所有匹配的内容",
                "recommendation": "建议先预览修改范围，确认无误后再执行"
            }
        
        # 添加确认选项
        clarification["options"] = [
            {"id": "confirm", "label": "确认执行"},
            {"id": "cancel", "label": "取消操作"},
            {"id": "preview", "label": "先预览影响范围"}
        ]
        
        return clarification
    
    def _handle_delete_operation(
        self,
        clarification: Dict[str, Any]
    ) -> Dict[str, Any]:
        """处理删除操作
        
        Args:
            clarification: 原始澄清信息
            
        Returns:
            增强的澄清信息
        """
        # 添加警告信息
        clarification["warning"] = {
            "level": "high",
            "message": "删除操作不可撤销（除非回滚到之前的版本）",
            "recommendation": "请确认要删除的内容"
        }
        
        # 添加确认选项
        clarification["options"] = [
            {"id": "confirm_delete", "label": "确认删除"},
            {"id": "cancel", "label": "取消操作"}
        ]
        
        return clarification
