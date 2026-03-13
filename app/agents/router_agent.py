"""
Router Agent - 路由决策智能体
负责根据意图决定下一步动作（澄清/检索/结束）
"""
from typing import Dict, Any
from sqlalchemy.orm import Session

from app.nodes.intent_clarifier import IntentClarifierNode


def create_router_agent(db: Session):
    """创建路由决策智能体"""
    return RouterAgent(db)


class RouterAgent:
    """路由决策智能体
    
    职责：
    1. 检查意图是否需要澄清
    2. 检测跨段落引用
    3. 检测大范围修改
    4. 决定下一步动作（clarify/retrieve/end）
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.clarifier = IntentClarifierNode(db)
    
    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行路由决策
        
        Args:
            state: 工作流状态
            
        Returns:
            更新后的状态，包含路由决策
        """
        intent = state.get("intent")
        intent_confidence = state.get("intent_confidence", 0.0)
        
        # 1. 验证意图存在
        if not intent:
            state["errors"] = state.get("errors", []) + [{
                "type": "no_intent",
                "message": "缺少意图信息"
            }]
            state["next_action"] = "end"
            return state
        
        # 2. 检查置信度
        if intent_confidence < 0.5:
            # 置信度过低，需要澄清
            state["needs_clarification"] = True
            state["clarification"] = {
                "type": "low_confidence",
                "message": "您的请求不够明确",
                "question": "请提供更详细的描述，例如：\n- 要修改哪个段落？\n- 要改成什么内容？",
                "severity": "medium"
            }
            state["next_action"] = "clarify"
            return state
        
        # 3. 使用 IntentClarifierNode 检查是否需要澄清
        try:
            clarifier_result = self.clarifier(state)
            
            # 如果需要澄清
            if clarifier_result.get("needs_clarification"):
                state["needs_clarification"] = True
                state["clarification"] = clarifier_result.get("clarification")
                state["next_action"] = "clarify"
                return state
            
            # 4. 意图明确，进入检索
            state["needs_clarification"] = False
            state["next_action"] = "retrieve"
            
            # 5. 添加调试信息
            if state.get("debug_mode"):
                state["debug_info"] = state.get("debug_info", {})
                state["debug_info"]["router_agent"] = {
                    "decision": "retrieve",
                    "confidence": intent_confidence,
                    "clarification_checked": True
                }
            
            return state
            
        except Exception as e:
            state["errors"] = state.get("errors", []) + [{
                "type": "router_agent_error",
                "message": f"路由智能体执行失败: {str(e)}"
            }]
            state["next_action"] = "end"
            return state
