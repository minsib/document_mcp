from typing import Any, Dict, Optional
import time
import uuid

from sqlalchemy.orm import Session

from app.agents.edit_workflow_agents import create_edit_workflow_agents
from app.agents.runtime import ensure_workflow_trace, get_trace_metadata
from app.models import database as db_models
from app.models.schemas import CandidateResponse, ChatEditResponse
from app.monitoring.metrics import (
    edit_request_duration,
    edits_applied,
    edits_failed,
    edits_requested,
    workflow_duration,
    workflow_runs_total,
)
from app.services.memory import MemoryService
from app.skills.document_edit import DocumentEditSkillBundle


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
            except Exception:
                self.cache = None

        self.skill_bundle = DocumentEditSkillBundle(db, self.cache)
        self.workflow_agents = create_edit_workflow_agents(self.skill_bundle)
        self.memory_service = MemoryService(db, self.cache)
        self.last_trace: Dict[str, Any] = {
            "agents_used": [],
            "skills_used": [],
            "events": [],
        }
        self.last_operation_type = "unknown"
        self.last_memory_context: Dict[str, Any] = {}

    def execute(
        self,
        doc_id: str,
        session_id: str,
        user_id: str,
        user_message: str,
        user_selection: Optional[str] = None,
    ) -> ChatEditResponse:
        """执行编辑工作流（集成 Langfuse 追踪）"""
        workflow_name = "edit_workflow"
        started_at = time.time()
        operation_type = "unknown"
        terminal_status = "failed"
        request_recorded = False
        state: Dict[str, Any] = {}
        memory_context = self.memory_service.build_memory_context(
            user_id=user_id,
            doc_id=doc_id,
            session_id=session_id,
            user_message=user_message,
        )
        self.last_memory_context = memory_context

        def ensure_edit_request_recorded() -> None:
            nonlocal request_recorded
            if not request_recorded:
                edits_requested.labels(operation_type=operation_type).inc()
                request_recorded = True

        def record_edit_failed(error_type: str) -> None:
            ensure_edit_request_recorded()
            edits_failed.labels(operation_type=operation_type, error_type=error_type).inc()

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
                    "message": user_message,
                },
            )
            if trace:
                trace_id = trace.id
        except Exception as exc:
            print(f"Langfuse trace 创建失败: {exc}")

        active_rev = self.db.query(
            db_models.DocumentActiveRevision
        ).filter(
            db_models.DocumentActiveRevision.doc_id == uuid.UUID(doc_id)
        ).first()

        if not active_rev:
            record_edit_failed("doc_not_found")
            terminal_status = "failed"
            elapsed = time.time() - started_at
            edit_request_duration.labels(
                operation_type=operation_type,
                status=terminal_status,
            ).observe(elapsed)
            workflow_duration.labels(workflow=workflow_name, status="error").observe(elapsed)
            workflow_runs_total.labels(workflow=workflow_name, status="error").inc()
            if trace:
                try:
                    from app.services.langfuse_client import flush

                    flush()
                except Exception:
                    pass
            return ChatEditResponse(
                status="failed",
                session_id=session_id,
                message="文档不存在",
                error={"code": "doc_not_found", "message": "文档不存在"},
            )

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
            "trace_id": trace_id,
            "user_preferences": memory_context["preferences"],
            "document_preferences": memory_context["document_preferences"],
            "editing_rules": memory_context["editing_rules"],
            "retrieved_memories": memory_context["retrieved_memories"],
            "working_memory": memory_context["working_memory"],
            "memory_context": memory_context["prompt_context"],
            "memory_summary": memory_context["summary"],
        }
        ensure_workflow_trace(state)

        try:
            state = self.workflow_agents["intent_agent"].invoke(state)
            operation_type = self._extract_operation_type(state)
            ensure_edit_request_recorded()
            if state.get("error"):
                record_edit_failed(self._extract_error_type(state.get("error"), "intent_parse_error"))
                terminal_status = "failed"
                return self._handle_error(state)

            state = self.workflow_agents["clarify_agent"].invoke(state)
            if state.get("needs_clarification"):
                clarification = state["clarification"]
                terminal_status = "need_clarification"
                self._sync_working_memory_snapshot(
                    session_id=session_id,
                    user_id=user_id,
                    doc_id=doc_id,
                    user_message=user_message,
                    status=terminal_status,
                    extra={"clarification": clarification},
                )
                return ChatEditResponse(
                    status="need_clarification",
                    session_id=session_id,
                    message=clarification["message"],
                    clarification={
                        "type": clarification["type"],
                        "question": clarification["question"],
                        "options": clarification.get("options", []),
                        "severity": clarification["severity"],
                    },
                )

            state = self.workflow_agents["retrieval_agent"].invoke(state)
            candidates = state.get("candidates", [])
            selection = state.get("selection")

            if not candidates:
                record_edit_failed("no_candidates")
                terminal_status = "failed"
                self._sync_working_memory_snapshot(
                    session_id=session_id,
                    user_id=user_id,
                    doc_id=doc_id,
                    user_message=user_message,
                    status=terminal_status,
                    extra={"reason": "no_candidates"},
                )
                return ChatEditResponse(
                    status="failed",
                    session_id=session_id,
                    message="未找到匹配的内容，请提供更具体的描述",
                    error={"code": "no_candidates", "message": "未找到匹配的内容"},
                )

            if selection and selection.need_user_disambiguation:
                terminal_status = "need_disambiguation"
                self._sync_working_memory_snapshot(
                    session_id=session_id,
                    user_id=user_id,
                    doc_id=doc_id,
                    user_message=user_message,
                    status=terminal_status,
                    extra={
                        "disambiguation_required": True,
                        "candidate_count": len(selection.candidates_for_user),
                    },
                )
                return ChatEditResponse(
                    status="need_disambiguation",
                    session_id=session_id,
                    candidates=[
                        CandidateResponse(
                            block_id=c.block_id,
                            snippet=c.snippet,
                            heading_context=c.heading_context,
                            order_index=c.order_index,
                        )
                        for c in selection.candidates_for_user
                    ],
                    message="找到多个可能的位置，请选择要修改的段落",
                )

            if not selection or not selection.targets:
                record_edit_failed("no_target")
                terminal_status = "failed"
                self._sync_working_memory_snapshot(
                    session_id=session_id,
                    user_id=user_id,
                    doc_id=doc_id,
                    user_message=user_message,
                    status=terminal_status,
                    extra={"reason": "no_target"},
                )
                return ChatEditResponse(
                    status="failed",
                    session_id=session_id,
                    message="无法定位目标内容",
                    error={"code": "no_target", "message": "无法定位目标内容"},
                )

            state = self.workflow_agents["planning_agent"].invoke(state)
            if state.get("error") or state.get("errors"):
                record_edit_failed(self._extract_error_type(state.get("error"), "planner_error"))
                terminal_status = "failed"
                return self._handle_error(state)

            state = self.workflow_agents["preview_agent"].invoke(state)
            if state.get("error") or state.get("errors"):
                record_edit_failed(self._extract_error_type(state.get("error"), "preview_error"))
                terminal_status = "failed"
                return self._handle_error(state)

            if state.get("need_user_action") == "confirm_preview":
                message = "请确认以下修改"
                warnings = state.get("warnings", [])
                if warnings:
                    warning_msgs = []
                    for warning in warnings:
                        if warning["type"] == "semantic_conflict":
                            warning_msgs.append(f"⚠️ {warning['message']}")
                    if warning_msgs:
                        message += "\n\n" + "\n".join(warning_msgs)

                terminal_status = "need_confirm"
                self._sync_working_memory_snapshot(
                    session_id=session_id,
                    user_id=user_id,
                    doc_id=doc_id,
                    user_message=user_message,
                    status=terminal_status,
                    extra={
                        "pending_confirmation": {
                            "confirm_token": state.get("confirm_token"),
                            "preview_hash": state.get("preview_hash"),
                            "preview": state.get("preview_diff"),
                        }
                    },
                )
                return ChatEditResponse(
                    status="need_confirm",
                    session_id=session_id,
                    preview=state["preview_diff"],
                    confirm_token=state["confirm_token"],
                    preview_hash=state["preview_hash"],
                    message=message,
                )

            state = self.workflow_agents["apply_agent"].invoke(state)
            if state.get("error") or state.get("errors"):
                record_edit_failed(self._extract_error_type(state.get("error"), "apply_error"))
                terminal_status = "failed"
                return self._handle_error(state)

            apply_result = state["apply_result"]
            new_rev_id = apply_result["new_rev_id"] if isinstance(apply_result, dict) else apply_result.new_rev_id
            export_md = self._export_document(new_rev_id)
            edits_applied.labels(operation_type=operation_type).inc()
            terminal_status = "applied"
            self._sync_working_memory_snapshot(
                session_id=session_id,
                user_id=user_id,
                doc_id=doc_id,
                user_message=user_message,
                status=terminal_status,
                extra={"new_rev_id": new_rev_id},
            )

            preview_diff = state["preview_diff"]
            diff_summary = preview_diff.get("diffs") if isinstance(preview_diff, dict) else preview_diff.diffs
            total_changes = preview_diff.get("total_changes") if isinstance(preview_diff, dict) else preview_diff.total_changes

            return ChatEditResponse(
                status="applied",
                session_id=session_id,
                new_rev_id=new_rev_id,
                diff_summary=diff_summary,
                export_md=export_md,
                message=f"已成功修改 {total_changes} 处内容",
            )

        except Exception as exc:
            if trace:
                try:
                    trace.update(
                        output={"error": str(exc)},
                        level="ERROR",
                    )
                except Exception:
                    pass

            record_edit_failed("workflow_error")
            terminal_status = "failed"
            self._sync_working_memory_snapshot(
                session_id=session_id,
                user_id=user_id,
                doc_id=doc_id,
                user_message=user_message,
                status=terminal_status,
                extra={"error": str(exc)},
            )
            return ChatEditResponse(
                status="failed",
                session_id=session_id,
                message=f"处理失败: {str(exc)}",
                error={"code": "workflow_error", "message": str(exc)},
            )
        finally:
            self.last_trace = get_trace_metadata(state) if state else {
                "agents_used": [],
                "skills_used": [],
                "events": [],
            }
            self.last_operation_type = operation_type
            ensure_edit_request_recorded()
            elapsed = time.time() - started_at
            edit_request_duration.labels(
                operation_type=operation_type,
                status=terminal_status,
            ).observe(elapsed)
            workflow_status = "success" if terminal_status in {
                "applied",
                "need_confirm",
                "need_disambiguation",
                "need_clarification",
            } else "error"
            workflow_duration.labels(workflow=workflow_name, status=workflow_status).observe(elapsed)
            workflow_runs_total.labels(workflow=workflow_name, status=workflow_status).inc()

            if trace:
                try:
                    from app.services.langfuse_client import flush

                    flush()
                except Exception:
                    pass

    def _handle_error(self, state: Dict[str, Any]) -> ChatEditResponse:
        """处理错误"""
        error = state.get("error")
        errors = state.get("errors") or []
        session_id = state.get("session_id")
        if isinstance(error, dict):
            return ChatEditResponse(
                status="failed",
                session_id=session_id,
                message=error.get("message", "处理失败"),
                error=error,
            )
        if hasattr(error, "model_dump"):
            error_dict = error.model_dump()
            return ChatEditResponse(
                status="failed",
                session_id=session_id,
                message=error_dict.get("message", "处理失败"),
                error=error_dict,
            )
        if errors:
            first_error = errors[0]
            if isinstance(first_error, dict):
                error_code = first_error.get("code") or first_error.get("type") or "workflow_error"
                error_message = first_error.get("message") or "处理失败"
                return ChatEditResponse(
                    status="failed",
                    session_id=session_id,
                    message=error_message,
                    error={"code": error_code, **first_error},
                )
            return ChatEditResponse(
                status="failed",
                session_id=session_id,
                message=str(first_error),
                error={"code": "workflow_error", "message": str(first_error)},
            )
        return ChatEditResponse(
            status="failed",
            session_id=session_id,
            message=str(error) if error else "处理失败",
            error={"code": "unknown_error", "message": str(error) if error else "未知错误"},
        )

    def _extract_operation_type(self, state: Dict[str, Any]) -> str:
        """从状态中提取编辑操作类型"""
        intent = state.get("intent")
        if not intent:
            return "unknown"
        if isinstance(intent, dict):
            return intent.get("operation", "unknown")
        return getattr(intent, "operation", "unknown")

    def _extract_error_type(self, error: Any, fallback: str) -> str:
        """从错误对象中提取稳定的错误类型"""
        if isinstance(error, dict):
            return error.get("code") or fallback
        if hasattr(error, "code"):
            return getattr(error, "code") or fallback
        return fallback

    def _export_document(self, rev_id: str) -> str:
        """导出文档"""
        blocks = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == uuid.UUID(rev_id)
        ).order_by(db_models.BlockVersion.order_index).all()

        markdown_parts = [block.content_md for block in blocks]
        return "\n\n".join(markdown_parts)

    def _sync_working_memory_snapshot(
        self,
        *,
        session_id: str,
        user_id: str,
        doc_id: str,
        user_message: str,
        status: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        snapshot = self.memory_service.get_working_memory(session_id) or {}
        snapshot.update({
            "user_id": user_id,
            "doc_id": doc_id,
            "current_goal": user_message,
            "last_status": status,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        if status not in {"need_confirm"}:
            snapshot.pop("pending_confirmation", None)
        if status not in {"need_clarification"}:
            snapshot.pop("clarification", None)
        if status not in {"need_disambiguation"}:
            snapshot.pop("disambiguation_required", None)
        if extra:
            snapshot.update(extra)
        self.memory_service.set_working_memory(session_id, snapshot, ttl=86400)
