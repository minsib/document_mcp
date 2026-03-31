"""
Workflow agent runtime primitives.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping


WorkflowState = Dict[str, Any]
SkillHandler = Callable[[WorkflowState], WorkflowState]
AgentStrategy = Callable[[WorkflowState, Mapping[str, "WorkflowSkill"]], WorkflowState]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_workflow_trace(state: WorkflowState) -> Dict[str, Any]:
    """Ensure workflow trace metadata exists on state."""
    trace = state.setdefault("_workflow_trace", {})
    trace.setdefault("agents_used", [])
    trace.setdefault("skills_used", [])
    trace.setdefault("events", [])
    return trace


def record_trace_event(
    state: WorkflowState,
    *,
    kind: str,
    name: str,
    status: str,
    detail: Dict[str, Any] | None = None,
) -> None:
    """Record a workflow trace event."""
    trace = ensure_workflow_trace(state)
    collection = "agents_used" if kind == "agent" else "skills_used"
    if name not in trace[collection]:
        trace[collection].append(name)

    event = {
        "kind": kind,
        "name": name,
        "status": status,
        "timestamp": _utc_now(),
    }
    if detail:
        event["detail"] = detail
    trace["events"].append(event)


def get_trace_metadata(state: WorkflowState) -> Dict[str, Any]:
    """Return a serializable view of workflow trace metadata."""
    trace = ensure_workflow_trace(state)
    return {
        "agents_used": list(trace["agents_used"]),
        "skills_used": list(trace["skills_used"]),
        "events": list(trace["events"]),
    }


@dataclass(slots=True)
class WorkflowSkill:
    """Composable workflow skill wrapper."""

    name: str
    handler: SkillHandler
    description: str = ""

    def execute(self, state: WorkflowState) -> WorkflowState:
        record_trace_event(state, kind="skill", name=self.name, status="started")
        try:
            next_state = self.handler(state)
            record_trace_event(next_state, kind="skill", name=self.name, status="completed")
            return next_state
        except Exception as exc:
            record_trace_event(
                state,
                kind="skill",
                name=self.name,
                status="failed",
                detail={"error": str(exc)},
            )
            raise


@dataclass(slots=True)
class WorkflowAgent:
    """Composable workflow agent wrapper."""

    name: str
    skills: Dict[str, WorkflowSkill] = field(default_factory=dict)
    strategy: AgentStrategy | None = None
    description: str = ""

    def invoke(self, state: WorkflowState) -> WorkflowState:
        if self.strategy is None:
            raise ValueError(f"WorkflowAgent {self.name} has no strategy configured")

        record_trace_event(state, kind="agent", name=self.name, status="started")
        try:
            next_state = self.strategy(state, self.skills)
            record_trace_event(next_state, kind="agent", name=self.name, status="completed")
            return next_state
        except Exception as exc:
            record_trace_event(
                state,
                kind="agent",
                name=self.name,
                status="failed",
                detail={"error": str(exc)},
            )
            raise
