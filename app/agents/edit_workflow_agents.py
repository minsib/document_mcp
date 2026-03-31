"""
Workflow-agent wrappers for the document editing pipeline.
"""
from typing import Any, Dict

from app.agents.runtime import WorkflowAgent, WorkflowSkill
from app.skills.document_edit import DocumentEditSkillBundle


def _intent_strategy(state: Dict[str, Any], skills: Dict[str, WorkflowSkill]) -> Dict[str, Any]:
    return skills["parse_intent"].execute(state)


def _clarify_strategy(state: Dict[str, Any], skills: Dict[str, WorkflowSkill]) -> Dict[str, Any]:
    return skills["clarify_intent"].execute(state)


def _retrieval_strategy(state: Dict[str, Any], skills: Dict[str, WorkflowSkill]) -> Dict[str, Any]:
    state = skills["retrieve_candidates"].execute(state)
    return skills["verify_targets"].execute(state)


def _planning_strategy(state: Dict[str, Any], skills: Dict[str, WorkflowSkill]) -> Dict[str, Any]:
    return skills["plan_edits"].execute(state)


def _preview_strategy(state: Dict[str, Any], skills: Dict[str, WorkflowSkill]) -> Dict[str, Any]:
    return skills["generate_preview"].execute(state)


def _apply_strategy(state: Dict[str, Any], skills: Dict[str, WorkflowSkill]) -> Dict[str, Any]:
    return skills["apply_edits"].execute(state)


def create_edit_workflow_agents(skill_bundle: DocumentEditSkillBundle) -> Dict[str, WorkflowAgent]:
    """Create workflow agents backed by reusable skill wrappers."""
    skills = {
        "parse_intent": WorkflowSkill(
            name="parse_intent",
            handler=skill_bundle.parse_intent,
            description="Parse a user edit request into structured intent",
        ),
        "clarify_intent": WorkflowSkill(
            name="clarify_intent",
            handler=skill_bundle.clarify_intent,
            description="Decide whether the request needs clarification",
        ),
        "retrieve_candidates": WorkflowSkill(
            name="retrieve_candidates",
            handler=skill_bundle.retrieve_candidates,
            description="Retrieve relevant document blocks for an edit request",
        ),
        "verify_targets": WorkflowSkill(
            name="verify_targets",
            handler=skill_bundle.verify_targets,
            description="Verify retrieved candidates and select edit targets",
        ),
        "plan_edits": WorkflowSkill(
            name="plan_edits",
            handler=skill_bundle.plan_edits,
            description="Generate an edit plan for selected targets",
        ),
        "generate_preview": WorkflowSkill(
            name="generate_preview",
            handler=skill_bundle.generate_preview,
            description="Build a preview and confirmation token for planned edits",
        ),
        "apply_edits": WorkflowSkill(
            name="apply_edits",
            handler=skill_bundle.apply_edits,
            description="Apply an approved edit plan to the active revision",
        ),
    }

    return {
        "intent_agent": WorkflowAgent(
            name="intent_agent",
            skills={"parse_intent": skills["parse_intent"]},
            strategy=_intent_strategy,
            description="Intent understanding agent",
        ),
        "clarify_agent": WorkflowAgent(
            name="clarify_agent",
            skills={"clarify_intent": skills["clarify_intent"]},
            strategy=_clarify_strategy,
            description="Clarification policy agent",
        ),
        "retrieval_agent": WorkflowAgent(
            name="retrieval_agent",
            skills={
                "retrieve_candidates": skills["retrieve_candidates"],
                "verify_targets": skills["verify_targets"],
            },
            strategy=_retrieval_strategy,
            description="Candidate retrieval and verification agent",
        ),
        "planning_agent": WorkflowAgent(
            name="planning_agent",
            skills={"plan_edits": skills["plan_edits"]},
            strategy=_planning_strategy,
            description="Edit planning agent",
        ),
        "preview_agent": WorkflowAgent(
            name="preview_agent",
            skills={"generate_preview": skills["generate_preview"]},
            strategy=_preview_strategy,
            description="Preview generation agent",
        ),
        "apply_agent": WorkflowAgent(
            name="apply_agent",
            skills={"apply_edits": skills["apply_edits"]},
            strategy=_apply_strategy,
            description="Persistence and revision apply agent",
        ),
    }
