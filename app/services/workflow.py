from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models import database as db_models
from app.models.schemas import CandidateResponse, ChatEditResponse
from app.monitoring.metrics import (
    edit_request_duration,
    edits_applied,
    edits_failed,
    edits_requested,
)
from app.services.langgraph_workflow import LangGraphWorkflowExecutor
from app.services.memory import MemoryService


class EditWorkflow:
    """LangGraph-backed edit workflow facade used by API handlers."""

    def __init__(self, db: Session, cache_manager=None):
        self.db = db
        self.cache = cache_manager
        self.memory_service = MemoryService(db, cache_manager)
        self.executor = LangGraphWorkflowExecutor(db, cache_manager)
        self.last_trace: Dict[str, Any] = {"nodes_used": [], "routes": [], "events": []}
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
        started_at = time.time()
        memory_context = self.memory_service.build_memory_context(
            user_id=user_id,
            doc_id=doc_id,
            session_id=session_id,
            user_message=user_message,
        )
        self.last_memory_context = memory_context

        trace_id = None
        try:
            from app.services.langfuse_client import create_trace

            trace = create_trace(
                name="document_edit_workflow",
                user_id=user_id,
                session_id=session_id,
                metadata={"doc_id": doc_id, "message": user_message},
            )
            if trace:
                trace_id = trace.id
        except Exception:
            trace_id = None

        result = self.executor.execute(
            doc_id=doc_id,
            session_id=session_id,
            user_id=user_id,
            user_message=user_message,
            user_selection=user_selection,
            memory_context=memory_context["prompt_context"],
            working_memory=memory_context["working_memory"],
            user_preferences=memory_context["preferences"],
            document_preferences=memory_context["document_preferences"],
            editing_rules=memory_context["editing_rules"],
            retrieved_memories=memory_context["retrieved_memories"],
            memory_summary=memory_context["summary"],
            trace_id=trace_id,
        )

        self.last_trace = result.get("trace", {"nodes_used": [], "routes": [], "events": []})
        self.last_operation_type = self._extract_operation_type(result, user_message)

        status = result.get("status", "failed")
        elapsed = time.time() - started_at
        edits_requested.labels(operation_type=self.last_operation_type).inc()
        edit_request_duration.labels(
            operation_type=self.last_operation_type,
            status=status,
        ).observe(elapsed)

        if status == "applied":
            edits_applied.labels(operation_type=self.last_operation_type).inc()
        elif status == "failed":
            error = result.get("error") or {}
            edits_failed.labels(
                operation_type=self.last_operation_type,
                error_type=error.get("code", "workflow_error"),
            ).inc()

        return self._to_response(result)

    def _to_response(self, result: Dict[str, Any]) -> ChatEditResponse:
        status = result.get("status", "failed")
        if status == "need_disambiguation":
            return ChatEditResponse(
                status="need_disambiguation",
                session_id=result.get("session_id"),
                candidates=[
                    CandidateResponse(**candidate)
                    for candidate in result.get("candidates", [])
                ],
                message=result.get("message", "找到多个候选"),
            )
        if status == "need_confirm":
            return ChatEditResponse(
                status="need_confirm",
                session_id=result.get("session_id"),
                preview=result.get("preview"),
                confirm_token=result.get("confirm_token"),
                preview_hash=result.get("preview_hash"),
                message=result.get("message", "请确认以下修改"),
            )
        if status == "need_clarification":
            return ChatEditResponse(
                status="need_clarification",
                session_id=result.get("session_id"),
                clarification=result.get("clarification"),
                message=result.get("message", "需要更多信息"),
            )
        if status == "applied":
            return ChatEditResponse(
                status="applied",
                session_id=result.get("session_id"),
                new_rev_id=result.get("new_rev_id"),
                diff_summary=result.get("diff_summary"),
                export_md=result.get("export_md"),
                message=result.get("message", "修改已应用"),
            )
        return ChatEditResponse(
            status="failed",
            session_id=result.get("session_id"),
            error=result.get("error"),
            message=result.get("message", "修改失败"),
        )

    def _export_document(self, rev_id: str) -> str:
        blocks = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == uuid.UUID(rev_id)
        ).order_by(db_models.BlockVersion.order_index).all()
        return "\n\n".join((block.content_md or "") for block in blocks)

    def _extract_operation_type(self, result: Dict[str, Any], user_message: str) -> str:
        if result.get("trace"):
            for event in result["trace"].get("events", []):
                detail = event.get("detail") or {}
                if detail.get("operation"):
                    return detail["operation"]
        lowered = (user_message or "").lower()
        if any(token in user_message for token in ["所有", "全部", "统一"]) and any(
            token in user_message for token in ["替换", "改成", "改为"]
        ):
            return "multi_replace"
        if "删除" in user_message or "去掉" in user_message:
            return "delete"
        if any(token in lowered for token in ["insert", "append"]) or any(token in user_message for token in ["增加", "添加", "插入"]):
            return "insert_after"
        return "replace"
