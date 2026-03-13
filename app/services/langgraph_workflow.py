"""
LangGraph 工作流 - 基于 LangGraph 的文档编辑工作流
"""
from typing import Dict, Any, TypedDict, Literal, Optional, List
from langgraph.graph import StateGraph, END
from sqlalchemy.orm import Session
from app.monitoring.metrics import workflow_duration, workflow_runs_total
import time

from app.agents.retrieval_agent import create_retrieval_agent
from app.models.schemas import Intent


# ============ State Definition ============

class WorkflowState(TypedDict, total=False):
    """工作流状态 - 所有字段都是可选的"""
    # 基础信息
    doc_id: str
    session_id: str
    user_id: str
    active_rev_id: str
    active_version: int
    
    # 用户输入
    user_message: str
    user_selection: Optional[str]
    user_clarification: Optional[dict]
    
    # 意图信息
    intent: Optional[dict]  # 改为 dict 而不是 Intent
    intent_confidence: float
    
    # 路由决策
    next_action: str  # 改为str而不是Literal，更灵活
    needs_clarification: bool
    needs_disambiguation: bool
    clarification: Optional[dict]
    
    # 检索结果
    candidates: List[dict]
    target_locations: List[dict]
    selected_target: Optional[dict]
    
    # 编辑计划
    edit_plan: Optional[dict]
    preview_diff: Optional[dict]
    
    # 执行结果
    new_rev_id: Optional[str]
    apply_result: Optional[dict]
    
    # 控制流
    retry_count: int
    max_retries: int
    warnings: List[dict]
    errors: List[dict]
    
    # 追踪信息
    trace_id: Optional[str]
    span_ids: dict



# ============ Node Functions ============

def intent_node(state: WorkflowState, db: Session) -> WorkflowState:
    """意图解析节点"""
    from app.agents.intent_agent import create_intent_agent
    
    agent = create_intent_agent(db)
    result = agent.invoke(state)
    
    # 更新状态而不是替换
    state.update(result)
    return state


def router_node(state: WorkflowState, db: Session) -> WorkflowState:
    """路由决策节点"""
    from app.agents.router_agent import create_router_agent
    
    agent = create_router_agent(db)
    result = agent.invoke(state)
    
    # 更新状态而不是替换
    state.update(result)
    return state


def clarify_node(state: WorkflowState, db: Session) -> WorkflowState:
    """澄清确认节点"""
    from app.agents.clarify_agent import create_clarify_agent
    
    agent = create_clarify_agent(db)
    result = agent.invoke(state)
    
    # 更新状态而不是替换
    state.update(result)
    return state


def retrieval_node(state: WorkflowState, db: Session) -> WorkflowState:
    """检索定位节点"""
    agent = create_retrieval_agent(db)
    result = agent.invoke(state)
    
    # 调试：打印结果
    print(f"DEBUG retrieval_node result keys: {result.keys()}")
    print(f"DEBUG selected_target in result: {'selected_target' in result}")
    if 'selected_target' in result:
        print(f"DEBUG selected_target value: {result['selected_target'] is not None}")
    
    # 更新状态
    state.update(result)
    
    # 调试：打印更新后的状态
    print(f"DEBUG state keys after update: {state.keys()}")
    print(f"DEBUG selected_target in state: {'selected_target' in state}")
    
    return state


def edit_node(state: WorkflowState, db: Session) -> WorkflowState:
    """编辑执行节点"""
    from app.nodes.planner import EditPlannerNode
    from app.nodes.preview import PreviewGeneratorNode
    from app.nodes.apply import ApplyEditsNode
    
    # 调试：打印进入edit_node时的状态
    print(f"DEBUG edit_node state keys: {state.keys()}")
    print(f"DEBUG selected_target in state: {'selected_target' in state}")
    if 'selected_target' in state:
        print(f"DEBUG selected_target value: {state.get('selected_target')}")
    
    selected_target = state.get("selected_target")
    if not selected_target:
        print("DEBUG: selected_target is None or empty!")
        state["errors"] = state.get("errors", []) + [{
            "type": "no_target",
            "message": "未选择目标块"
        }]
        state["next_action"] = "end"
        return state
    
    print("DEBUG: selected_target exists, proceeding with edit")
    
    # 1. 生成编辑计划
    planner = EditPlannerNode(db)
    state = planner(state)
    
    # Check if planner added errors
    if state.get("errors") and len(state["errors"]) > 0:
        print("DEBUG: planner added errors")
        state["next_action"] = "end"
        return state
    
    print(f"DEBUG: edit_plan generated: {state.get('edit_plan') is not None}")
    
    # 2. 生成预览
    preview_gen = PreviewGeneratorNode(db, None)
    state = preview_gen(state)
    
    # Check if preview generator added errors
    if state.get("errors") and len(state["errors"]) > 0:
        print("DEBUG: preview generator added errors")
        state["next_action"] = "end"
        return state
    
    print(f"DEBUG: preview_diff generated: {state.get('preview_diff') is not None}")
    
    # 3. 判断是否需要确认
    if state.get("need_user_action") == "confirm_preview":
        print("DEBUG: need user confirmation")
        state["next_action"] = "end"
        return state
    
    # 4. 执行修改
    apply_node = ApplyEditsNode(db)
    state = apply_node(state)
    
    # Check if apply node added errors
    if state.get("errors") and len(state["errors"]) > 0:
        print("DEBUG: apply node added errors")
        state["next_action"] = "end"
        return state
    
    print("DEBUG: apply completed successfully")
    # apply_result 已经在 state 中了
    
    state["next_action"] = "end"
    
    return state


# ============ Routing Functions ============

def route_decision(state: WorkflowState) -> str:
    """路由决策"""
    next_action = state.get("next_action", "end")
    
    if next_action == "clarify":
        return "clarify"
    elif next_action == "retrieve":
        return "retrieve"
    elif next_action == "edit":
        return "edit"
    else:
        return "end"


# ============ Workflow Creation ============

def create_workflow(db: Session):
    """创建 LangGraph 工作流"""
    
    # 创建状态图
    workflow = StateGraph(WorkflowState)
    
    # 添加节点（使用 lambda 传递 db）
    workflow.add_node("parse_intent", lambda state: intent_node(state, db))
    workflow.add_node("route_decision", lambda state: router_node(state, db))
    workflow.add_node("clarify_user", lambda state: clarify_node(state, db))
    workflow.add_node("retrieve_target", lambda state: retrieval_node(state, db))
    workflow.add_node("execute_edit", lambda state: edit_node(state, db))
    
    # 设置入口点
    workflow.set_entry_point("parse_intent")
    
    # 添加边
    workflow.add_edge("parse_intent", "route_decision")
    
    # 条件路由
    workflow.add_conditional_edges(
        "route_decision",
        route_decision,
        {
            "clarify": "clarify_user",
            "retrieve": "retrieve_target",
            "end": END
        }
    )
    
    workflow.add_edge("clarify_user", END)
    workflow.add_edge("retrieve_target", "execute_edit")
    workflow.add_edge("execute_edit", END)
    
    # 编译工作流
    return workflow.compile()


# ============ Workflow Executor ============

class LangGraphWorkflowExecutor:
    """LangGraph 工作流执行器"""
    
    def __init__(self, db: Session):
        self.db = db
        self.workflow = create_workflow(db)
    
    def execute(
        self,
        doc_id: str,
        session_id: str,
        user_id: str,
        user_message: str,
        user_selection: Optional[str] = None
    ) -> Dict[str, Any]:
        """执行工作流"""
        started_at = time.time()
        terminal_status = "failed"
        from app.models import database as db_models
        import uuid
        
        # 获取 active_revision
        active_rev = self.db.query(
            db_models.DocumentActiveRevision
        ).filter(
            db_models.DocumentActiveRevision.doc_id == uuid.UUID(doc_id)
        ).first()
        
        if not active_rev:
            terminal_status = "failed"
            elapsed = time.time() - started_at
            workflow_duration.labels(
                workflow="langgraph_edit_workflow",
                status="error"
            ).observe(elapsed)
            workflow_runs_total.labels(
                workflow="langgraph_edit_workflow",
                status="error"
            ).inc()
            return {
                "status": "failed",
                "message": "文档不存在",
                "error": {"code": "doc_not_found"}
            }
        
        # 初始化状态
        initial_state: WorkflowState = {
            "doc_id": doc_id,
            "session_id": session_id,
            "user_id": user_id,
            "active_rev_id": str(active_rev.rev_id),
            "active_version": active_rev.version,
            "user_message": user_message,
            "user_selection": user_selection,
            "user_clarification": None,
            "intent": None,
            "intent_confidence": 0.0,
            "next_action": "intent",
            "needs_clarification": False,
            "needs_disambiguation": False,
            "clarification": None,
            "candidates": [],
            "target_locations": [],
            "selected_target": None,
            "edit_plan": None,
            "preview_diff": None,
            "new_rev_id": None,
            "apply_result": None,
            "retry_count": 0,
            "max_retries": 2,
            "warnings": [],
            "errors": [],
            "trace_id": None,
            "span_ids": {}
        }
        
        try:
            # 执行工作流
            print(f"DEBUG: Starting workflow execution")
            result = self.workflow.invoke(initial_state)
            print(f"DEBUG: Workflow completed, result keys: {result.keys() if isinstance(result, dict) else 'not a dict'}")
            
            # 格式化返回结果
            response = self._format_response(result)
            if isinstance(response, dict):
                terminal_status = response.get("status", "failed")
            return response
            
        except KeyError as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"工作流执行失败 (KeyError): {error_detail}")
            terminal_status = "failed"
            return {
                "status": "failed",
                "message": f"工作流执行失败: {str(e)}",
                "error": {"code": "workflow_error", "message": str(e), "detail": error_detail}
            }
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"工作流执行失败: {error_detail}")
            terminal_status = "failed"
            return {
                "status": "failed",
                "message": f"工作流执行失败: {str(e)}",
                "error": {"code": "workflow_error", "message": str(e), "detail": error_detail}
            }
        finally:
            elapsed = time.time() - started_at
            workflow_status = "success" if terminal_status in {
                "applied", "need_confirm", "need_disambiguation", "need_clarification"
            } else "error"
            workflow_duration.labels(
                workflow="langgraph_edit_workflow",
                status=workflow_status
            ).observe(elapsed)
            workflow_runs_total.labels(
                workflow="langgraph_edit_workflow",
                status=workflow_status
            ).inc()
    
    def _format_response(self, state: WorkflowState) -> Dict[str, Any]:
        """格式化响应"""
        try:
            from app.models.schemas import ChatEditResponse, CandidateResponse
            
            # 检查错误
            if state.get("errors"):
                return ChatEditResponse(
                    status="failed",
                    message=state["errors"][0].get("message", "处理失败"),
                    error=state["errors"][0]
                ).model_dump()
            
            # 需要澄清
            if state.get("needs_clarification"):
                clarification = state["clarification"]
                return ChatEditResponse(
                    status="need_clarification",
                    message=clarification["message"],
                    clarification={
                        "type": clarification["type"],
                        "question": clarification["question"],
                        "options": clarification.get("options", []),
                        "severity": clarification["severity"]
                    }
                ).model_dump()
            
            # 需要消歧
            if state.get("needs_disambiguation"):
                return ChatEditResponse(
                    status="need_disambiguation",
                    candidates=[
                        CandidateResponse(
                            block_id=loc["block_id"],
                            snippet=loc["plain_text"][:200],
                            heading_context=loc["heading_context"],
                            order_index=loc["order_index"]
                        )
                        for loc in state["target_locations"]
                    ],
                    message="找到多个可能的位置，请选择要修改的段落"
                ).model_dump()
            
            # 需要确认预览
            if state.get("preview_diff") and not state.get("apply_result"):
                message = "请确认以下修改"
                if state.get("warnings"):
                    warning_msgs = [f"⚠️ {w['message']}" for w in state["warnings"]]
                    message += "\n\n" + "\n".join(warning_msgs)
                
                preview_diff = state["preview_diff"]
                # 如果是对象，转换为字典
                if hasattr(preview_diff, 'model_dump'):
                    preview_dict = preview_diff.model_dump()
                elif isinstance(preview_diff, dict):
                    preview_dict = preview_diff
                else:
                    preview_dict = {}
                
                return ChatEditResponse(
                    status="need_confirm",
                    preview=preview_dict,
                    confirm_token="token_placeholder",  # TODO: 生成真实 token
                    preview_hash="hash_placeholder",  # TODO: 生成真实 hash
                    message=message
                ).model_dump()
            
            # 执行成功
            if "apply_result" in state and state["apply_result"]:
                apply_result = state["apply_result"]
                preview_diff = state.get("preview_diff")
                
                # 处理 diff_summary
                diff_summary = []
                if preview_diff:
                    if hasattr(preview_diff, 'diffs'):
                        diff_summary = preview_diff.diffs
                    elif isinstance(preview_diff, dict):
                        diff_summary = preview_diff.get("diffs", [])
                
                # 处理 new_rev_id
                new_rev_id = state.get("new_rev_id")
                if not new_rev_id:
                    if hasattr(apply_result, 'new_rev_id'):
                        new_rev_id = apply_result.new_rev_id
                    elif isinstance(apply_result, dict):
                        new_rev_id = apply_result.get("new_rev_id")
                
                return ChatEditResponse(
                    status="applied",
                    new_rev_id=new_rev_id,
                    diff_summary=diff_summary,
                    message=f"已成功修改内容"
                ).model_dump()
            
            # 默认失败
            return ChatEditResponse(
                status="failed",
                message="未知错误",
                error={"code": "unknown_error"}
            ).model_dump()
        
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"格式化响应失败: {error_detail}")
            print(f"State keys: {state.keys() if isinstance(state, dict) else 'not a dict'}")
            print(f"State content: {state}")
            return {
                "status": "failed",
                "message": f"处理失败: {str(e)}",
                "error": {"code": "format_error", "message": str(e), "detail": error_detail}
            }
