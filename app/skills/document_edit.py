"""
Document editing skills used by workflow agents.
"""
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models.schemas import TargetSelection
from app.nodes.apply import ApplyEditsNode
from app.nodes.intent_clarifier import IntentClarifierNode
from app.nodes.intent_parser import IntentParserNode
from app.nodes.planner import EditPlannerNode
from app.nodes.preview import PreviewGeneratorNode
from app.nodes.verifier import VerifierNode
from app.services.retriever import HybridRetriever


class DocumentEditSkillBundle:
    """Skill bundle backing the document edit workflow."""

    def __init__(self, db: Session, cache_manager: Any = None):
        self.db = db
        self.cache = cache_manager
        self.intent_parser = IntentParserNode()
        self.intent_clarifier = IntentClarifierNode(db)
        self.retriever = HybridRetriever(db)
        self.verifier = VerifierNode(db)
        self.planner = EditPlannerNode(db)
        self.preview_generator = PreviewGeneratorNode(db, cache_manager)
        self.apply_node = ApplyEditsNode(db)

    def parse_intent(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return self.intent_parser(state)

    def clarify_intent(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return self.intent_clarifier(state)

    def retrieve_candidates(self, state: Dict[str, Any]) -> Dict[str, Any]:
        intent = state["intent"]
        candidates = self.retriever.search(
            query=state["user_message"],
            doc_id=state["doc_id"],
            rev_id=state["active_rev_id"],
            scope_hint=intent.scope_hint,
            top_k=10,
        )
        state["candidates"] = candidates
        return state

    def verify_targets(self, state: Dict[str, Any]) -> Dict[str, Any]:
        state = self.verifier(state)
        selection = state.get("selection")
        if isinstance(selection, TargetSelection) and selection.targets:
            primary = selection.targets[0]
            state["selected_target"] = {
                "block_id": primary.block_id,
                "evidence": primary.evidence.model_dump(),
                "confidence": primary.confidence,
            }
        return state

    def plan_edits(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return self.planner(state)

    def generate_preview(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return self.preview_generator(state)

    def apply_edits(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return self.apply_node(state)
