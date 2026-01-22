from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.nodes.intent_parser import IntentParserNode
from app.nodes.verifier import VerifierNode
from app.nodes.planner import EditPlannerNode
from app.nodes.preview import PreviewGeneratorNode
from app.nodes.apply import ApplyEditsNode
from app.services.retriever import HybridRetriever
from app.models.schemas import ChatEditResponse, CandidateResponse
from app.models import database as db_models
import uuid


class EditWorkflow:
    """编辑工作流"""
    
    def __init__(self, db: Session, cache_manager=None):
        self.db = db
        if cache_manager:
            self.cache = cache_manager
        else:
            try:
                from app.services.cache import get_cache_manager
                self.cache = get_cache_manager()
            except:
                self.cache = None
        
        # 初始化节点
        self.intent_parser = IntentParserNode()
        self.retriever = HybridRetriever(db)
        self.verifier = VerifierNode(db)
        self.planner = EditPlannerNode(db)
        self.preview_generator = PreviewGeneratorNode(db, self.cache)
        self.apply_node = ApplyEditsNode(db)
    
    def execute(
        self,
        doc_id: str,
        session_id: str,
        user_id: str,
        user_message: str,
        user_selection: Optional[str] = None
    ) -> ChatEditResponse:
        """执行编辑工作流（集成 Langfuse 追踪）"""
        
        # 创建 Langfuse Trace
        trace = None
        trace_id = None
        try:
            from app.services.langfuse_client import create_trace
            trace = create_trace(
                name="document_edit_workflow",
                user_id=user_id,
                session_id=session_id,
                metadata={
                    "doc_id": doc_id,
                    "message": user_message
                }
            )
            if trace:
                trace_id = trace.id
        except Exception as e:
            print(f"Langfuse trace 创建失败: {e}")
        
        # 获取 active_revision
        active_rev = self.db.query(
            db_models.DocumentActiveRevision
        ).filter(
            db_models.DocumentActiveRevision.doc_id == uuid.UUID(doc_id)
        ).first()
        
        if not active_rev:
            return ChatEditResponse(
                status="failed",
                message="文档不存在",
                error={"code": "doc_not_found", "message": "文档不存在"}
            )
        
        # 初始化状态
        state = {
            "doc_id": doc_id,
            "session_id": session_id,
            "user_id": user_id,
            "active_rev_id": str(active_rev.rev_id),
            "active_version": active_rev.version,
            "user_message": user_message,
            "user_selection": user_selection,
            "retry_count": 0,
            "max_retries": 2,
            "trace_id": trace_id  # 传递 trace_id
        }
        
        try:
            # 1. 解析意图
            state = self.intent_parser(state)
            if state.get("error"):
                return self._handle_error(state)
            
            # 2. 检索候选
            intent = state["intent"]
            try:
                candidates = self.retriever.search(
                    query=user_message,
                    doc_id=doc_id,
                    rev_id=state["active_rev_id"],
                    scope_hint=intent.scope_hint,
                    top_k=10
                )
            except Exception as e:
                # 如果检索失败，回滚事务并重试
                print(f"检索失败: {e}")
                self.db.rollback()
                candidates = []
            
            state["candidates"] = candidates
            
            if not candidates:
                return ChatEditResponse(
                    status="failed",
                    message="未找到匹配的内容，请提供更具体的描述",
                    error={"code": "no_candidates", "message": "未找到匹配的内容"}
                )
            
            # 3. 验证并选择
            state = self.verifier(state)
            selection = state.get("selection")
            
            if selection and selection.need_user_disambiguation:
                return ChatEditResponse(
                    status="need_disambiguation",
                    candidates=[
                        CandidateResponse(
                            block_id=c.block_id,
                            snippet=c.snippet,
                            heading_context=c.heading_context,
                            order_index=c.order_index
                        )
                        for c in selection.candidates_for_user
                    ],
                    message="找到多个可能的位置，请选择要修改的段落"
                )
            
            if not selection or not selection.targets:
                return ChatEditResponse(
                    status="failed",
                    message="无法定位目标内容",
                    error={"code": "no_target", "message": "无法定位目标内容"}
                )
            
            # 4. 生成编辑计划
            state = self.planner(state)
            if state.get("error"):
                return self._handle_error(state)
            
            # 5. 生成预览
            state = self.preview_generator(state)
            if state.get("error"):
                return self._handle_error(state)
            
            # 6. 判断是否需要确认
            if state.get("need_user_action") == "confirm_preview":
                return ChatEditResponse(
                    status="need_confirm",
                    preview=state["preview_diff"],
                    confirm_token=state["confirm_token"],
                    preview_hash=state["preview_hash"],
                    message="请确认以下修改"
                )
            
            # 7. 直接应用（低风险操作）
            state = self.apply_node(state)
            if state.get("error"):
                return self._handle_error(state)
            
            # 8. 导出文档
            export_md = self._export_document(state["apply_result"].new_rev_id)
            
            return ChatEditResponse(
                status="applied",
                new_rev_id=state["apply_result"].new_rev_id,
                diff_summary=state["preview_diff"].diffs,
                export_md=export_md,
                message=f"已成功修改 {state['preview_diff'].total_changes} 处内容"
            )
            
        except Exception as e:
            # 记录错误到 Langfuse
            if trace:
                try:
                    trace.update(
                        output={"error": str(e)},
                        level="ERROR"
                    )
                except:
                    pass
            
            return ChatEditResponse(
                status="failed",
                message=f"处理失败: {str(e)}",
                error={"code": "workflow_error", "message": str(e)}
            )
        finally:
            # 刷新 Langfuse 缓冲区
            if trace:
                try:
                    from app.services.langfuse_client import flush
                    flush()
                except:
                    pass
    
    def _handle_error(self, state: Dict[str, Any]) -> ChatEditResponse:
        """处理错误"""
        error = state.get("error")
        if isinstance(error, dict):
            return ChatEditResponse(
                status="failed",
                message=error.get("message", "处理失败"),
                error=error
            )
        elif hasattr(error, 'model_dump'):
            error_dict = error.model_dump()
            return ChatEditResponse(
                status="failed",
                message=error_dict.get("message", "处理失败"),
                error=error_dict
            )
        else:
            return ChatEditResponse(
                status="failed",
                message=str(error) if error else "处理失败",
                error={"code": "unknown_error", "message": str(error) if error else "未知错误"}
            )
    
    def _export_document(self, rev_id: str) -> str:
        """导出文档"""
        blocks = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == uuid.UUID(rev_id)
        ).order_by(db_models.BlockVersion.order_index).all()
        
        markdown_parts = [block.content_md for block in blocks]
        return '\n\n'.join(markdown_parts)
from app.models import database as db_models
