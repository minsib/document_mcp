"""
LangGraph-backed document editing workflow.
"""
from __future__ import annotations

import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.models import database as db_models
from app.monitoring.metrics import (
    record_retrieval_metrics,
    record_workflow_route,
    track_workflow_node_metric,
    workflow_active_runs,
    workflow_duration,
    workflow_runs_total,
    retrieval_evidence_validation_total,
)
from app.nodes.apply import ApplyEditsNode
from app.nodes.bulk_discover import BulkDiscoverNode
from app.nodes.bulk_preview import BulkPreviewNode
from app.nodes.intent_clarifier import IntentClarifierNode
from app.nodes.intent_parser import IntentParserNode
from app.nodes.planner import EditPlannerNode
from app.nodes.preview import PreviewGeneratorNode
from app.nodes.verifier import VerifierNode
from app.services.retriever import HybridRetriever


class WorkflowState(TypedDict, total=False):
    doc_id: str
    session_id: str
    user_id: str
    active_rev_id: str
    active_rev_no: int
    active_version: int
    user_message: str
    user_selection: Optional[str]
    user_confirmation: Optional[bool]
    intent: Any
    candidates: List[Any]
    retrieval_query: str
    selection: Any
    selected_target: Dict[str, Any]
    edit_plan: Dict[str, Any]
    preview_diff: Dict[str, Any]
    confirm_token: str
    preview_hash: str
    _confirm_payload: Dict[str, Any]
    apply_result: Dict[str, Any]
    new_rev_id: str
    export_md: str
    retry_count: int
    max_retries: int
    error: Dict[str, Any]
    errors: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]
    clarification: Dict[str, Any]
    needs_clarification: bool
    need_user_action: Optional[str]
    start_time: float
    step_timings: Dict[str, float]
    trace_id: Optional[str]
    memory_context: str
    working_memory: Dict[str, Any]
    user_preferences: List[Any]
    document_preferences: List[Any]
    editing_rules: List[Any]
    retrieved_memories: List[Any]
    memory_summary: Dict[str, Any]
    retrieval_mode: str
    _workflow_trace: Dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_trace(state: WorkflowState) -> Dict[str, Any]:
    trace = state.setdefault("_workflow_trace", {})
    trace.setdefault("nodes_used", [])
    trace.setdefault("routes", [])
    trace.setdefault("events", [])
    return trace


def _record_node_event(state: WorkflowState, node: str, status: str, detail: Optional[Dict[str, Any]] = None) -> None:
    trace = _ensure_trace(state)
    if node not in trace["nodes_used"]:
        trace["nodes_used"].append(node)
    event = {
        "kind": "node",
        "name": node,
        "status": status,
        "timestamp": _utc_now(),
    }
    if detail:
        event["detail"] = detail
    trace["events"].append(event)


def _record_route(state: WorkflowState, route: str) -> None:
    trace = _ensure_trace(state)
    trace["routes"].append({"route": route, "timestamp": _utc_now()})
    record_workflow_route("langgraph_edit_workflow", route)


def _extract_error(state: WorkflowState) -> Optional[Dict[str, Any]]:
    error = state.get("error")
    if error:
        return error
    errors = state.get("errors") or []
    if not errors:
        return None
    latest = errors[-1]
    return {
        "code": latest.get("type", "workflow_error"),
        "message": latest.get("message", "workflow_error"),
    }


def _set_error(state: WorkflowState, code: str, message: str) -> WorkflowState:
    state["error"] = {"code": code, "message": message}
    return state


def _selection_confidence(selection: Any) -> Optional[float]:
    if not selection:
        return None
    targets = getattr(selection, "targets", None) or []
    if not targets:
        return None
    return float(targets[0].confidence)


def _selection_outcome(state: WorkflowState) -> str:
    selection = state.get("selection")
    if not state.get("candidates"):
        return "no_candidates"
    if selection and getattr(selection, "need_user_disambiguation", False):
        return "disambiguation"
    confidence = _selection_confidence(selection)
    if confidence is not None and confidence < 0.7:
        return "retry"
    if confidence is not None:
        return "auto_selected" if not state.get("user_selection") else "user_selected"
    return "failed"


class LangGraphWorkflowExecutor:
    """LangGraph workflow executor for edit requests."""

    workflow_name = "langgraph_edit_workflow"

    def __init__(self, db: Session, cache_manager=None):
        self.db = db
        self.cache = cache_manager
        self.intent_parser = IntentParserNode()
        self.intent_clarifier = IntentClarifierNode(db)
        self.retriever = HybridRetriever(db)
        self.verifier = VerifierNode(db)
        self.bulk_discover = BulkDiscoverNode(db)
        self.bulk_preview = BulkPreviewNode(db)
        self.planner = EditPlannerNode(db)
        self.preview_generator = PreviewGeneratorNode(db, cache_manager)
        self.apply_node = ApplyEditsNode(db)
        self.workflow = self._build_workflow()

    def execute(
        self,
        *,
        doc_id: str,
        session_id: str,
        user_id: str,
        user_message: str,
        user_selection: Optional[str] = None,
        memory_context: str = "",
        working_memory: Optional[Dict[str, Any]] = None,
        user_preferences: Optional[List[Any]] = None,
        document_preferences: Optional[List[Any]] = None,
        editing_rules: Optional[List[Any]] = None,
        retrieved_memories: Optional[List[Any]] = None,
        memory_summary: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        started_at = time.time()
        workflow_active_runs.labels(workflow=self.workflow_name).inc()
        active_rev = self.db.query(db_models.DocumentActiveRevision).filter(
            db_models.DocumentActiveRevision.doc_id == uuid.UUID(doc_id)
        ).first()
        if not active_rev:
            workflow_active_runs.labels(workflow=self.workflow_name).dec()
            workflow_runs_total.labels(workflow=self.workflow_name, status="error").inc()
            workflow_duration.labels(workflow=self.workflow_name, status="error").observe(0.0)
            return {
                "status": "failed",
                "message": "文档不存在",
                "error": {"code": "doc_not_found", "message": "文档不存在"},
            }

        active_revision = self.db.query(db_models.DocumentRevision).filter(
            db_models.DocumentRevision.rev_id == active_rev.rev_id
        ).first()

        state: WorkflowState = {
            "doc_id": doc_id,
            "session_id": session_id,
            "user_id": user_id,
            "active_rev_id": str(active_rev.rev_id),
            "active_rev_no": active_revision.rev_no if active_revision else 0,
            "active_version": active_rev.version,
            "user_message": user_message,
            "user_selection": user_selection,
            "retry_count": 0,
            "max_retries": 2,
            "start_time": started_at,
            "step_timings": {},
            "trace_id": trace_id,
            "memory_context": memory_context,
            "working_memory": working_memory or {},
            "user_preferences": user_preferences or [],
            "document_preferences": document_preferences or [],
            "editing_rules": editing_rules or [],
            "retrieved_memories": retrieved_memories or [],
            "memory_summary": memory_summary or {},
            "warnings": [],
            "errors": [],
            "need_user_action": None,
            "retrieval_mode": "hybrid",
            "_workflow_trace": {},
        }
        _ensure_trace(state)

        terminal_status = "error"
        try:
            result = self.workflow.invoke(state)
            response = self._format_response(result)
            terminal_status = response.get("status", "failed")
            return response
        except Exception as exc:
            error_message = str(exc)
            return {
                "status": "failed",
                "message": f"工作流执行失败: {error_message}",
                "error": {"code": "workflow_error", "message": error_message},
            }
        finally:
            elapsed = time.time() - started_at
            metric_status = "success" if terminal_status in {"need_confirm", "need_disambiguation", "need_clarification", "applied"} else "error"
            workflow_duration.labels(workflow=self.workflow_name, status=metric_status).observe(elapsed)
            workflow_runs_total.labels(workflow=self.workflow_name, status=metric_status).inc()
            workflow_active_runs.labels(workflow=self.workflow_name).dec()

    def _build_workflow(self):
        graph = StateGraph(WorkflowState)

        graph.add_node("intent_parse", self._intent_parse_node)
        graph.add_node("clarify_intent", self._clarify_node)
        graph.add_node("retrieve_candidates", self._retrieve_node)
        graph.add_node("verify_and_select", self._verify_node)
        graph.add_node("retry_locate", self._retry_locate_node)
        graph.add_node("plan_edits", self._plan_node)
        graph.add_node("generate_preview", self._preview_node)
        graph.add_node("apply_edits", self._apply_node)
        graph.add_node("export_document", self._export_node)
        graph.add_node("bulk_discover", self._bulk_discover_node)
        graph.add_node("bulk_preview", self._bulk_preview_node)
        graph.add_node("handle_error", self._handle_error_node)

        graph.set_entry_point("intent_parse")
        graph.add_edge("intent_parse", "clarify_intent")
        graph.add_conditional_edges(
            "clarify_intent",
            self._route_after_clarify,
            {
                "end": END,
                "bulk_discover": "bulk_discover",
                "retrieve_candidates": "retrieve_candidates",
            },
        )
        graph.add_edge("retrieve_candidates", "verify_and_select")
        graph.add_conditional_edges(
            "verify_and_select",
            self._route_after_verify,
            {
                "end": END,
                "retry_locate": "retry_locate",
                "plan_edits": "plan_edits",
                "handle_error": "handle_error",
            },
        )
        graph.add_edge("retry_locate", "retrieve_candidates")
        graph.add_edge("plan_edits", "generate_preview")
        graph.add_conditional_edges(
            "generate_preview",
            self._route_after_preview,
            {
                "end": END,
                "apply_edits": "apply_edits",
            },
        )
        graph.add_conditional_edges(
            "apply_edits",
            self._route_after_apply,
            {
                "retry_locate": "retry_locate",
                "export_document": "export_document",
                "handle_error": "handle_error",
            },
        )
        graph.add_edge("bulk_discover", "bulk_preview")
        graph.add_edge("bulk_preview", END)
        graph.add_edge("handle_error", END)
        graph.add_edge("export_document", END)

        return graph.compile()

    def _run_node(self, state: WorkflowState, node_name: str, handler) -> WorkflowState:
        start_time = time.time()
        _record_node_event(state, node_name, "started")
        try:
            with track_workflow_node_metric(self.workflow_name, node_name):
                next_state = handler(state)
            duration = time.time() - start_time
            next_state.setdefault("step_timings", {})[node_name] = duration
            _record_node_event(next_state, node_name, "completed", {"duration_ms": round(duration * 1000, 2)})
            return next_state
        except Exception as exc:
            duration = time.time() - start_time
            state.setdefault("step_timings", {})[node_name] = duration
            _record_node_event(state, node_name, "failed", {"duration_ms": round(duration * 1000, 2), "error": str(exc)})
            raise

    def _intent_parse_node(self, state: WorkflowState) -> WorkflowState:
        next_state = self._run_node(state, "intent_parse", self.intent_parser)
        intent = next_state.get("intent")
        if intent:
            _record_node_event(
                next_state,
                "intent_parse",
                "result",
                {
                    "operation": getattr(intent, "operation", None),
                    "risk": getattr(intent, "risk", None),
                },
            )
        return next_state

    def _clarify_node(self, state: WorkflowState) -> WorkflowState:
        return self._run_node(state, "clarify_intent", self.intent_clarifier)

    def _retrieve_node(self, state: WorkflowState) -> WorkflowState:
        def _handler(current_state: WorkflowState) -> WorkflowState:
            intent = current_state.get("intent")
            if not intent:
                return _set_error(current_state, "missing_intent", "缺少意图解析结果")

            query = self._build_query(intent, current_state["user_message"])
            candidates = self.retriever.search(
                query=query,
                doc_id=current_state["doc_id"],
                rev_id=current_state["active_rev_id"],
                scope_hint=getattr(intent, "scope_hint", None),
                top_k=10 if current_state.get("retry_count", 0) == 0 else 15,
            )
            current_state["candidates"] = candidates
            current_state["retrieval_query"] = query
            mode = current_state.get("retrieval_mode", "hybrid")
            top_score = candidates[0].score if candidates else None
            record_retrieval_metrics(
                mode=mode,
                candidate_count=len(candidates),
                top_score=top_score,
            )
            return current_state

        return self._run_node(state, "retrieve_candidates", _handler)

    def _verify_node(self, state: WorkflowState) -> WorkflowState:
        next_state = self._run_node(state, "verify_and_select", self.verifier)
        selection = next_state.get("selection")
        confidence = _selection_confidence(selection)
        selection_source = "user" if next_state.get("user_selection") else "model"
        outcome = _selection_outcome(next_state)
        record_retrieval_metrics(
            mode=next_state.get("retrieval_mode", "hybrid"),
            candidate_count=len(next_state.get("candidates") or []),
            top_score=(next_state.get("candidates") or [None])[0].score if next_state.get("candidates") else None,
            selected_confidence=confidence,
            selection_source=selection_source if confidence is not None else None,
            outcome=outcome,
        )
        if selection and getattr(selection, "targets", None):
            evidence = selection.targets[0].evidence
            block = self.db.query(db_models.BlockVersion).filter(
                db_models.BlockVersion.block_id == uuid.UUID(selection.targets[0].block_id),
                db_models.BlockVersion.rev_id == uuid.UUID(next_state["active_rev_id"]),
            ).first()
            if block and evidence.text and evidence.text in (block.plain_text or ""):
                retrieval_evidence_validation_total.labels(result="matched").inc()
            else:
                retrieval_evidence_validation_total.labels(result="mismatched").inc()
            _record_node_event(
                next_state,
                "verify_and_select",
                "result",
                {
                    "selected_block_id": selection.targets[0].block_id,
                    "confidence": selection.targets[0].confidence,
                    "need_user_disambiguation": getattr(selection, "need_user_disambiguation", False),
                },
            )
        return next_state

    def _retry_locate_node(self, state: WorkflowState) -> WorkflowState:
        def _handler(current_state: WorkflowState) -> WorkflowState:
            current_state["retry_count"] = current_state.get("retry_count", 0) + 1
            current_state["retrieval_mode"] = "retry"
            intent = current_state.get("intent")
            if intent and getattr(intent, "scope_hint", None):
                relaxed = deepcopy(intent)
                relaxed.scope_hint.heading = None
                relaxed.scope_hint.nearby = None
                current_state["intent"] = relaxed
            return current_state

        return self._run_node(state, "retry_locate", _handler)

    def _plan_node(self, state: WorkflowState) -> WorkflowState:
        return self._run_node(state, "plan_edits", self.planner)

    def _preview_node(self, state: WorkflowState) -> WorkflowState:
        return self._run_node(state, "generate_preview", self.preview_generator)

    def _apply_node(self, state: WorkflowState) -> WorkflowState:
        return self._run_node(state, "apply_edits", self.apply_node)

    def _export_node(self, state: WorkflowState) -> WorkflowState:
        def _handler(current_state: WorkflowState) -> WorkflowState:
            apply_result = current_state.get("apply_result") or {}
            new_rev_id = apply_result.get("new_rev_id")
            if not new_rev_id:
                return _set_error(current_state, "missing_revision", "缺少新的版本号")
            blocks = self.db.query(db_models.BlockVersion).filter(
                db_models.BlockVersion.rev_id == uuid.UUID(new_rev_id)
            ).order_by(db_models.BlockVersion.order_index).all()
            current_state["export_md"] = "\n\n".join((block.content_md or "") for block in blocks)
            return current_state

        return self._run_node(state, "export_document", _handler)

    def _bulk_discover_node(self, state: WorkflowState) -> WorkflowState:
        def _handler(current_state: WorkflowState) -> WorkflowState:
            intent = current_state.get("intent")
            candidates = self.bulk_discover.discover(
                intent,
                current_state["doc_id"],
                current_state["active_rev_id"],
                max_changes=100,
            )
            current_state["candidates"] = candidates
            if not candidates:
                _set_error(current_state, "no_matches", "未找到匹配的内容")
            return current_state

        return self._run_node(state, "bulk_discover", _handler)

    def _bulk_preview_node(self, state: WorkflowState) -> WorkflowState:
        def _handler(current_state: WorkflowState) -> WorkflowState:
            intent = current_state.get("intent")
            preview, edit_plan = self.bulk_preview.generate_preview(
                intent,
                current_state.get("candidates", []),
                current_state["active_rev_id"],
                current_state["doc_id"],
            )
            if not preview.diffs:
                return _set_error(current_state, "no_changes", "没有需要修改的内容")

            plan_dict = edit_plan.model_dump()
            plan_dict["estimated_impact"] = "high" if preview.total_changes > 20 else "medium"
            plan_dict["requires_confirmation"] = True
            current_state["edit_plan"] = plan_dict
            current_state["preview_diff"] = preview.model_dump()

            # Reuse the single-preview token generation for strong confirmation checks.
            current_state = self.preview_generator(current_state)
            current_state["need_user_action"] = "confirm_preview"
            return current_state

        return self._run_node(state, "bulk_preview", _handler)

    def _handle_error_node(self, state: WorkflowState) -> WorkflowState:
        def _handler(current_state: WorkflowState) -> WorkflowState:
            error = _extract_error(current_state)
            if error:
                current_state["error"] = error
            elif not current_state.get("error"):
                current_state["error"] = {"code": "workflow_error", "message": "处理失败"}
            return current_state

        return self._run_node(state, "handle_error", _handler)

    def _route_after_clarify(self, state: WorkflowState) -> str:
        if state.get("needs_clarification"):
            _record_route(state, "clarify_intent:end")
            return "end"

        intent = state.get("intent")
        operation = getattr(intent, "operation", None)
        if operation == "multi_replace":
            _record_route(state, "clarify_intent:bulk_discover")
            return "bulk_discover"

        _record_route(state, "clarify_intent:retrieve_candidates")
        return "retrieve_candidates"

    def _route_after_verify(self, state: WorkflowState) -> str:
        selection = state.get("selection")
        if not state.get("candidates"):
            _record_route(state, "verify_and_select:handle_error")
            return "handle_error"

        if selection and getattr(selection, "need_user_disambiguation", False):
            state["need_user_action"] = "select_candidate"
            _record_route(state, "verify_and_select:end_disambiguation")
            return "end"

        confidence = _selection_confidence(selection)
        if confidence is not None and confidence < 0.7 and state.get("retry_count", 0) < state.get("max_retries", 0):
            _record_route(state, "verify_and_select:retry_locate")
            return "retry_locate"

        if confidence is None:
            _set_error(state, "no_target", "无法定位目标内容")
            _record_route(state, "verify_and_select:handle_error")
            return "handle_error"

        if confidence < 0.7:
            state["need_user_action"] = "select_candidate"
            if selection and not getattr(selection, "candidates_for_user", None):
                selection.candidates_for_user = (state.get("candidates") or [])[:5]
                selection.need_user_disambiguation = True
            _record_route(state, "verify_and_select:end_low_confidence")
            return "end"

        _record_route(state, "verify_and_select:plan_edits")
        return "plan_edits"

    def _route_after_preview(self, state: WorkflowState) -> str:
        if state.get("need_user_action") == "confirm_preview":
            _record_route(state, "generate_preview:end_confirm")
            return "end"
        _record_route(state, "generate_preview:apply_edits")
        return "apply_edits"

    def _route_after_apply(self, state: WorkflowState) -> str:
        error = _extract_error(state)
        if not error and state.get("apply_result"):
            _record_route(state, "apply_edits:export_document")
            return "export_document"

        if error and error.get("code") in {"concurrent_edit", "validation_failed"} and state.get("retry_count", 0) < state.get("max_retries", 0):
            active_rev = self.db.query(db_models.DocumentActiveRevision).filter(
                db_models.DocumentActiveRevision.doc_id == uuid.UUID(state["doc_id"])
            ).first()
            if active_rev:
                state["active_rev_id"] = str(active_rev.rev_id)
                state["active_version"] = active_rev.version
            state["retry_count"] = state.get("retry_count", 0) + 1
            _record_route(state, "apply_edits:retry_locate")
            return "retry_locate"

        _record_route(state, "apply_edits:handle_error")
        return "handle_error"

    def _build_query(self, intent: Any, user_message: str) -> str:
        parts: List[str] = []
        scope_hint = getattr(intent, "scope_hint", None)
        heading = getattr(scope_hint, "heading", None) if scope_hint else None
        if heading:
            parts.append(heading)

        keywords = getattr(scope_hint, "keywords", None) if scope_hint else None
        if keywords:
            parts.extend([keyword for keyword in keywords if keyword])

        query = " ".join(dict.fromkeys(parts)).strip()
        return query or user_message

    def _format_response(self, state: WorkflowState) -> Dict[str, Any]:
        error = _extract_error(state)
        preview = state.get("preview_diff")
        selection = state.get("selection")

        if state.get("needs_clarification"):
            clarification = state.get("clarification", {})
            return {
                "status": "need_clarification",
                "session_id": state.get("session_id"),
                "message": clarification.get("message", "需要更多信息"),
                "clarification": clarification,
                "trace": state.get("_workflow_trace", {}),
            }

        if state.get("need_user_action") == "select_candidate" and selection:
            return {
                "status": "need_disambiguation",
                "session_id": state.get("session_id"),
                "message": "找到多个可能的位置，请选择要修改的段落",
                "candidates": [
                    {
                        "block_id": candidate.block_id,
                        "snippet": candidate.snippet,
                        "heading_context": candidate.heading_context,
                        "order_index": candidate.order_index,
                    }
                    for candidate in getattr(selection, "candidates_for_user", []) or []
                ],
                "trace": state.get("_workflow_trace", {}),
            }

        if state.get("need_user_action") == "confirm_preview" and preview:
            return {
                "status": "need_confirm",
                "session_id": state.get("session_id"),
                "message": "请确认以下修改",
                "preview": preview,
                "confirm_token": state.get("confirm_token"),
                "preview_hash": state.get("preview_hash"),
                "trace": state.get("_workflow_trace", {}),
            }

        if state.get("apply_result"):
            return {
                "status": "applied",
                "session_id": state.get("session_id"),
                "message": f"已成功修改 {preview.get('total_changes', 0) if preview else 0} 处内容",
                "new_rev_id": state["apply_result"].get("new_rev_id"),
                "diff_summary": preview.get("diffs") if preview else [],
                "export_md": state.get("export_md"),
                "trace": state.get("_workflow_trace", {}),
            }

        return {
            "status": "failed",
            "session_id": state.get("session_id"),
            "message": error.get("message", "修改失败，请重试") if error else "修改失败，请重试",
            "error": error or {"code": "workflow_error", "message": "修改失败，请重试"},
            "trace": state.get("_workflow_trace", {}),
        }
